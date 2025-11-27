"""
FletX - Advanced Async/Sync HTTP Client for API requests
"""
import json
import asyncio
import logging
import threading
from pathlib import Path
from typing import (
    Any, Dict, Optional, Union, AsyncIterator, List, Callable, BinaryIO, Iterator
)
from dataclasses import dataclass, field
from time import monotonic
import random
from email.utils import parsedate_to_datetime
from functools import wraps
import aiohttp
import requests
from aiohttp import ClientTimeout, ClientResponse, ClientSession
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fletx.utils.exceptions import (
    NetworkError, RateLimitError, APIError
)

logger = logging.getLogger("fletx.http")


####
##      FILE INFO
#####
@dataclass
class FileInfo:
    """Information about an uploaded/downloaded file"""

    filename: str
    size: int
    content_type: str
    field_name: Optional[str] = None


####
##      HTTP RESPONSE
#####
@dataclass
class HTTPResponse:
    """Structured HTTP response container"""

    status: int
    headers: Dict[str, str]
    data: Union[Dict[str, Any], str, bytes]
    elapsed: float
    url: str
    files: List[FileInfo] = field(default_factory=list)
    cookies: Dict[str, str] = field(default_factory=dict)
    
    @property
    def ok(self) -> bool:
        """Check if response is successful (2xx status)"""

        return 200 <= self.status < 300
    
    @property
    def is_json(self) -> bool:
        """Check if response contains JSON data"""

        return isinstance(self.data, (dict, list))
    
    def json(self) -> Union[Dict[str, Any], List[Any]]:
        """Get JSON data from response"""

        if not self.is_json:
            raise ValueError("Response does not contain JSON data")
        return self.data
    
    def text(self) -> str:
        """Get text data from response"""

        # Bytes data
        if isinstance(self.data, bytes):
            return self.data.decode('utf-8')
        
        # Str 
        elif isinstance(self.data, str):
            return self.data
        
        # Json data
        elif isinstance(self.data, dict) and 'raw_response' in self.data:
            return self.data['raw_response']
        return str(self.data)


####
##      UPLOAD PROGRESS
#####
@dataclass
class UploadProgress:
    """Progress information for file uploads"""

    uploaded: int
    total: int
    percentage: float
    speed: float  # bytes per second
    filename: str


####
##      DOWNLOAD PROGRESS
#####
@dataclass
class DownloadProgress:
    """Progress information for file downloads"""

    downloaded: int
    total: int
    percentage: float
    speed: float  # bytes per second
    filename: str


####
##      FORM DATA CLASS
#####
class FormData(aiohttp.FormData):
    """Enhanced FormData with file support"""
    
    def add_file(
        self, 
        field_name: str, 
        file_path: Union[str, Path], 
        filename: Optional[str] = None, 
        content_type: Optional[str] = None
    ):
        """Add a file to the form data"""

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        filename = filename or file_path.name
        with open(file_path, 'rb') as f:
            content = f.read()
        
        self.add_field(
            field_name, 
            content, 
            filename = filename, 
            content_type = content_type
        )


####
##      MIDDLEWARE SYSTEM
#####
class Middleware:
    """Base middleware class"""
    
    async def before_request(
        self, 
        method: str, 
        url: str, **kwargs
    ) -> Dict[str, Any]:
        """Called before each request"""

        return kwargs
    
    async def after_response(
        self, 
        response: HTTPResponse
    ) -> HTTPResponse:
        """Called after each response"""

        return response
    
    async def on_error(
        self, 
        error: Exception
    ) -> Optional[Exception]:
        """Called when an error occurs. Return None to suppress the error."""

        return error


####
##      AUTHENTICATION MIDDLEWARE
#####
class AuthMiddleware(Middleware):
    """Authentication middleware"""
    
    def __init__(self, token: str, auth_type: str = "Bearer"):
        self.token = token
        self.auth_type = auth_type
    
    async def before_request(
        self, 
        method: str, 
        url: str, **kwargs
    ) -> Dict[str, Any]:
        """Authentication middleware."""

        headers = kwargs.get('headers', {})
        headers['Authorization'] = f"{self.auth_type} {self.token}"
        kwargs['headers'] = headers

        return kwargs


####
##      LOGGING MIDDLEWARE
#####
class LoggingMiddleware(Middleware):
    """Request/Response logging middleware"""
    
    def __init__(self, log_level: int = logging.INFO):
        self.log_level = log_level
    
    async def before_request(
        self, 
        method: str, 
        url: str, **kwargs
    ) -> Dict[str, Any]:
        
        logger.log(self.log_level, f"[REQUEST] {method} {url}")
        return kwargs
    
    async def after_response(
        self, 
        response: HTTPResponse
    ) -> HTTPResponse:
        
        logger.log(
            self.log_level, 
            f"[RESPONSE] {response.status} {response.url} ({response.elapsed:.2f}s)"
        )
        return response


####
##      MAIN HTTP CLIENT CLASS
#####
class HTTPClient:
    """Advanced asynchronous/synchronous HTTP client with enhanced features"""
    
    def __init__(
        self,
        base_url: str = "",
        default_headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        debug: bool = False,
        proxy: Optional[str] = None,
        pool_size: int = 100,
        verify_ssl: bool = True,
        follow_redirects: bool = True,
        max_redirects: int = 10,
        cookies: Optional[Dict[str, str]] = None,
        sync_mode: bool = False
    ):
        """
        Initialize the HTTP client with advanced configuration.
        
        Args:
            base_url: Base API endpoint
            default_headers: Default headers for all requests
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
            retry_delay: Initial delay between retries in seconds
            debug: Enable debug logging
            proxy: Proxy server URL
            pool_size: Connection pool size
            verify_ssl: Verify SSL certificates
            follow_redirects: Follow HTTP redirects
            max_redirects: Maximum number of redirects to follow
            cookies: Default cookies
            sync_mode: Use synchronous mode by default
        """

        self.base_url = base_url.rstrip('/') if base_url else ""
        self.default_headers = default_headers or {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "FletX-HTTPClient/1.0"
        }
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.debug = debug
        self.proxy = proxy
        self.pool_size = pool_size
        self.verify_ssl = verify_ssl
        self.follow_redirects = follow_redirects
        self.max_redirects = max_redirects
        self.default_cookies = cookies or {}
        self.sync_mode = sync_mode
        
        # Async components
        self._session: Optional[ClientSession] = None
        self.connector: Optional[aiohttp.TCPConnector] = None
        
        # Sync components
        self._sync_session: Optional[requests.Session] = None
        
        # Middleware
        self.middlewares: List[Middleware] = []
        
        # Progress callbacks
        self.upload_progress_callback: Optional[Callable[[UploadProgress], None]] = None
        self.download_progress_callback: Optional[Callable[[DownloadProgress], None]] = None
        
        # Rate limiting
        self.rate_limit_per_second: Optional[float] = None
        self._last_request_time: float = 0
        self._request_lock = asyncio.Lock()
        self._sync_request_lock = threading.Lock()

    def add_middleware(self, middleware: Middleware) -> 'HTTPClient':
        """Add middleware to the client"""

        self.middlewares.append(middleware)
        return self

    def set_auth(self, token: str, auth_type: str = "Bearer") -> 'HTTPClient':
        """Set authentication token"""

        self.add_middleware(AuthMiddleware(token, auth_type))
        return self

    def set_rate_limit(self, requests_per_second: float) -> 'HTTPClient':
        """Set rate limiting"""

        self.rate_limit_per_second = requests_per_second
        return self

    def set_upload_progress_callback(
        self, 
        callback: Callable[[UploadProgress], None]
    ) -> 'HTTPClient':
        """Set upload progress callback"""

        self.upload_progress_callback = callback
        return self

    def set_download_progress_callback(
        self, 
        callback: Callable[[DownloadProgress], None]
    ) -> 'HTTPClient':
        """Set download progress callback"""

        self.download_progress_callback = callback
        return self

    async def __aenter__(self) -> 'HTTPClient':

        await self.start_session()
        return self

    async def __aexit__(self, *exc) -> None:

        await self.close_session()

    def __enter__(self) -> 'HTTPClient':

        self.start_sync_session()
        return self

    def __exit__(self, *exc) -> None:

        self.close_sync_session()

    async def start_session(self) -> None:
        """Initialize the async client session"""

        if self._session is None or self._session.closed:
            if self.connector is None:
                self.connector = aiohttp.TCPConnector(
                    limit = self.pool_size,
                    force_close = False,
                    enable_cleanup_closed = True,
                    ssl = self.verify_ssl
                )
            
            timeout = ClientTimeout(total=self.timeout)
            self._session = ClientSession(
                connector = self.connector,
                timeout = timeout,
                headers = self.default_headers,
                cookies = self.default_cookies
            )

    def start_sync_session(self) -> None:
        """Initialize the sync client session"""

        if self._sync_session is None:
            self._sync_session = requests.Session()
            self._sync_session.headers.update(self.default_headers)
            self._sync_session.cookies.update(self.default_cookies)
            
            # Configure retries for sync session
            retry_strategy = Retry(
                total = self.max_retries,
                backoff_factor = self.retry_delay,
                status_forcelist = [429, 500, 502, 503, 504]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_maxsize=self.pool_size)
            self._sync_session.mount("http://", adapter)
            self._sync_session.mount("https://", adapter)

    async def close_session(self) -> None:
        """Close the async client session"""

        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def close_sync_session(self) -> None:
        """Close the sync client session"""

        if self._sync_session:
            self._sync_session.close()
            self._sync_session = None

    async def _apply_middlewares_before(
        self, 
        method: str, 
        url: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """Apply middlewares before request"""

        for middleware in self.middlewares:
            kwargs = await middleware.before_request(method, url, **kwargs)
        return kwargs

    async def _apply_middlewares_after(
        self, 
        response: HTTPResponse
    ) -> HTTPResponse:
        """Apply middlewares after response"""

        for middleware in self.middlewares:
            response = await middleware.after_response(response)
        return response

    async def _apply_middlewares_error(
        self, error: Exception
    ) -> Optional[Exception]:
        """Apply middlewares on error"""

        for middleware in self.middlewares:
            error = await middleware.on_error(error)
            if error is None:
                break
        return error

    async def _rate_limit_check(self) -> None:
        """Check and enforce rate limiting"""

        if self.rate_limit_per_second is None:
            return
        
        async with self._request_lock:
            current_time = monotonic()
            time_since_last = current_time - self._last_request_time
            min_interval = 1.0 / self.rate_limit_per_second
            
            if time_since_last < min_interval:
                await asyncio.sleep(min_interval - time_since_last)
            
            self._last_request_time = monotonic()

    def _sync_rate_limit_check(self) -> None:
        """Synchronous rate limiting check"""

        if self.rate_limit_per_second is None:
            return
        
        with self._sync_request_lock:
            import time
            current_time = time.monotonic()
            time_since_last = current_time - self._last_request_time
            min_interval = 1.0 / self.rate_limit_per_second
            
            if time_since_last < min_interval:
                time.sleep(min_interval - time_since_last)
            
            self._last_request_time = time.monotonic()

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint"""

        if endpoint.startswith(('http://', 'https://')):
            return endpoint
        
        if self.base_url:
            return f"{self.base_url}/{endpoint.lstrip('/')}"
        return endpoint

    async def _process_files_async(
        self, 
        files: Dict[str, Any], 
        data: Optional[Dict] = None, 
        json_data: Optional[Dict] = None
    ) -> aiohttp.FormData:
        """Process files for async upload"""

        form_data = aiohttp.FormData()
        
        # Add regular form fields
        if data and isinstance(data, dict):
            for key, value in data.items():
                form_data.add_field(key, str(value))
        
        # Add JSON data as form field if needed
        if json_data:
            form_data.add_field('json_payload', json.dumps(json_data))
        
        # Add files
        for field_name, file_info in files.items():

            # Provided file is a path
            if isinstance(file_info, (str, Path)):
                # File path
                file_path = Path(file_info)
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found: {file_path}")
                
                # Read file content
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                form_data.add_field(
                    field_name,
                    content,
                    filename = file_path.name
                )
            
            # Content file as tuple
            elif isinstance(file_info, tuple):

                if len(file_info) == 2:
                    filename, content = file_info
                    form_data.add_field(
                        field_name, 
                        content, 
                        filename = filename
                    )

                elif len(file_info) == 3:
                    filename, content, content_type = file_info
                    form_data.add_field(
                        field_name, 
                        content, 
                        filename = filename, 
                        content_type = content_type
                    )
            
            # File-like object
            elif hasattr(file_info, 'read'):
                content = file_info.read()
                filename = getattr(file_info, 'name', f'{field_name}_file')
                form_data.add_field(field_name, content, filename = filename)

            else:
                form_data.add_field(field_name, file_info)
        
        return form_data

    def _process_files_sync(
        self, files: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process files for sync upload"""

        processed_files = {}
        
        for field_name, file_info in files.items():

            # File path
            if isinstance(file_info, (str, Path)):
                file_path = Path(file_info)
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found: {file_path}")
                
                processed_files[field_name] = open(file_path, 'rb')
            
            # File Tuple (filename, content, [content_type])
            elif isinstance(file_info, tuple):
                if len(file_info) == 2:
                    filename, content = file_info

                    if isinstance(content, (str, bytes)):
                        processed_files[field_name] = (filename, content)

                elif len(file_info) == 3:
                    filename, content, content_type = file_info
                    processed_files[field_name] = (filename, content, content_type)

            # File-like object
            elif hasattr(file_info, 'read'):
                processed_files[field_name] = file_info

            else:
                processed_files[field_name] = file_info
        
        return processed_files

    async def _request_async(
        self,
        method: str,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Union[Dict[str, Any], List[Any]]] = None,
        files: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> HTTPResponse:
        """Execute async HTTP request"""

        url = self._build_url(endpoint)
        merged_headers = {**self.default_headers, **(headers or {})}
        
        # Apply middlewares
        request_kwargs = await self._apply_middlewares_before(
            method, url, headers=merged_headers, params=params, 
            data=data, json_data=json_data, files=files, **kwargs
        )
        
        # Rate limiting
        await self._rate_limit_check()
        
        # Handle file uploads
        if files:
            data = await self._process_files_async(files, data, json_data)
            merged_headers.pop('Content-Type', None)
            json_data = None
        
        start_time = monotonic()
        last_exception = None
        
        retryable_statuses = {429, 500, 502, 503, 504}
        for attempt in range(self.max_retries + 1):
            try:
                if not self._session or self._session.closed:
                    await self.start_session()

                async with self._session.request(
                    method = method,
                    url = url,
                    headers = merged_headers,
                    params = params,
                    data = data,
                    json = json_data,
                    proxy = self.proxy,
                    allow_redirects = self.follow_redirects,
                    max_redirects = self.max_redirects,
                    **kwargs
                ) as response:
                    elapsed = monotonic() - start_time
                    
                    # Process response content
                    content_type = response.headers.get('Content-Type', '')

                    # Json data
                    if 'application/json' in content_type:
                        response_data = await response.json()
                    
                    # Text data
                    elif 'text/' in content_type:
                        response_data = await response.text()
                    
                    # Byte data (probably a file)
                    else:
                        response_data = await response.read()

                    if self.debug:
                        logger.debug(f"Response ({response.status}) in {elapsed:.2f}s")

                    # Handle retryable responses (429/5xx)
                    if response.status in retryable_statuses and attempt < self.max_retries:
                        # Respect Retry-After header if present
                        retry_after = response.headers.get('Retry-After')
                        wait_time = self._compute_retry_wait(attempt, retry_after)
                        if self.debug:
                            logger.warning(
                                f"Retryable status {response.status}. Attempt {attempt + 1}/{self.max_retries}. "
                                f"Waiting {wait_time:.2f}s before retry."
                            )
                        await asyncio.sleep(wait_time)
                        continue
                    
                    http_response = HTTPResponse(
                        status = response.status,
                        headers = dict(response.headers),
                        data = response_data,
                        elapsed = elapsed,
                        url = str(response.url),
                        cookies = dict(response.cookies)
                    )
                    
                    # Apply after middlewares
                    http_response = await self._apply_middlewares_after(http_response)
                    
                    return http_response

            except Exception as e:
                last_exception = e
                error = await self._apply_middlewares_error(e)
                
                if error is None:
                    # Error was handled by middleware
                    continue
                
                if attempt == self.max_retries:
                    if isinstance(e, (aiohttp.ClientError, aiohttp.ClientPayloadError)):
                        raise NetworkError(
                            message=f"Network error: {str(e)}",
                            original_exception=e
                        ) from e
                    raise e
                
                retry_wait = self.retry_delay * (2 ** attempt) * (1 + random.uniform(0, 0.25))
                if self.debug:
                    logger.warning(
                        f"Attempt {attempt + 1} failed. Retrying in {retry_wait:.1f}s. Error: {str(e)}"
                    )
                await asyncio.sleep(retry_wait)

    def _request_sync(
        self,
        method: str,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Union[Dict[str, Any], List[Any]]] = None,
        files: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> HTTPResponse:
        """Execute sync HTTP request"""

        url = self._build_url(endpoint)
        merged_headers = {**self.default_headers, **(headers or {})}
        
        # Rate limiting
        self._sync_rate_limit_check()
        
        # Handle file uploads
        if files:
            files = self._process_files_sync(files)
            merged_headers.pop('Content-Type', None)
        
        if not self._sync_session:
            self.start_sync_session()
        
        start_time = monotonic()
        
        try:
            response = self._sync_session.request(
                method = method,
                url = url,
                headers = merged_headers,
                params = params,
                data = data,
                json = json_data,
                files = files,
                proxies = {'http': self.proxy, 'https': self.proxy} if self.proxy else None,
                verify = self.verify_ssl,
                allow_redirects = self.follow_redirects,
                timeout = self.timeout,
                **kwargs
            )
            
            elapsed = monotonic() - start_time
            
            # Process response content
            content_type = response.headers.get('Content-Type', '')

            # Json data
            if 'application/json' in content_type:
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = {"raw_response": response.text}

            # Text data
            elif 'text/' in content_type:
                response_data = response.text

            else:
                response_data = response.content
            
            return HTTPResponse(
                status = response.status_code,
                headers = dict(response.headers),
                data = response_data,
                elapsed = elapsed,
                url = response.url,
                cookies = dict(response.cookies)
            )
            
        except requests.RequestException as e:
            raise NetworkError(
                message = f"Network error: {str(e)}",
                original_exception = e
            ) from e
        
        finally:
            # Close file handles if we opened them
            if files:
                for file_obj in files.values():
                    if hasattr(file_obj, 'close'):
                        file_obj.close()

    # Unified request method that chooses async or sync
    def request(
        self,
        method: str,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Union[Dict[str, Any], List[Any]]] = None,
        files: Optional[Dict[str, Any]] = None,
        sync: Optional[bool] = None,
        **kwargs
    ) -> Union[HTTPResponse, asyncio.Future[HTTPResponse]]:
        """
        Universal request method that can work both sync and async
        
        Args:
            sync: If True, force synchronous execution. If False, force async. 
                  If None, use the client's default mode.
        """

        use_sync = sync if sync is not None else self.sync_mode
        
        if use_sync:
            return self._request_sync(
                method, 
                endpoint, 
                headers, 
                params, 
                data, 
                json_data, 
                files, 
                **kwargs
            )
        
        else:
            return self._request_async(
                method, 
                endpoint, 
                headers, 
                params, 
                data, 
                json_data, 
                files, 
                **kwargs
            )

    def _compute_retry_wait(self, attempt: int, retry_after: Optional[str]) -> float:
        """
        Compute retry wait time using exponential backoff with jitter and
        honoring Retry-After header when available.
        """
        # Respect Retry-After if present and valid
        if retry_after:
            # Retry-After can be seconds or an HTTP-date
            try:
                seconds = int(retry_after)
                return max(0.0, float(seconds))
            except ValueError:
                try:
                    from datetime import datetime, timezone
                    retry_dt = parsedate_to_datetime(retry_after)
                    # Ensure timezone-aware comparison
                    if retry_dt.tzinfo is None:
                        retry_dt = retry_dt.replace(tzinfo=timezone.utc)
                    now = datetime.now(tz=retry_dt.tzinfo)
                    delay = (retry_dt - now).total_seconds()
                    # If computed negative due to clock differences, fallback to base
                    if delay > 0:
                        return delay
                except Exception:
                    pass

        # Exponential backoff with small jitter
        base = self.retry_delay * (2 ** attempt)
        return base * (1 + random.uniform(0, 0.25))

    # Convenience methods
    def get(
        self, 
        endpoint: str, 
        **kwargs
    ) -> Union[HTTPResponse, asyncio.Future[HTTPResponse]]:
        """Perform GET request"""

        return self.request("GET", endpoint, **kwargs)

    def post(
        self, 
        endpoint: str, 
        **kwargs
    ) -> Union[HTTPResponse, asyncio.Future[HTTPResponse]]:
        """Perform POST request"""

        return self.request("POST", endpoint, **kwargs)

    def put(
        self, 
        endpoint: str, 
        **kwargs
    ) -> Union[HTTPResponse, asyncio.Future[HTTPResponse]]:
        """Perform PUT request"""

        return self.request("PUT", endpoint, **kwargs)

    def delete(
        self, 
        endpoint: str, 
        **kwargs
    ) -> Union[HTTPResponse, asyncio.Future[HTTPResponse]]:
        """Perform DELETE request"""

        return self.request("DELETE", endpoint, **kwargs)

    def patch(
        self, 
        endpoint: str, 
        **kwargs
    ) -> Union[HTTPResponse, asyncio.Future[HTTPResponse]]:
        """Perform PATCH request"""

        return self.request("PATCH", endpoint, **kwargs)

    # File-specific methods
    async def upload_file(
        self,
        endpoint: str,
        file_path: Union[str, Path],
        field_name: str = "file",
        additional_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> HTTPResponse:
        """Upload a single file"""

        files = {field_name: file_path}
        return await self._request_async(
            "POST", 
            endpoint, 
            files = files, 
            data = additional_data, 
            **kwargs
        )

    async def download_file(
        self,
        endpoint: str,
        file_path: Union[str, Path],
        **kwargs
    ) -> HTTPResponse:
        """Download a file"""

        response = await self._request_async("GET", endpoint, **kwargs)
        
        if response.ok and isinstance(response.data, bytes):
            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'wb') as f:
                f.write(response.data)
        
        return response

    async def stream_download(
        self,
        endpoint: str,
        file_path: Union[str, Path],
        chunk_size: int = 8192,
        **kwargs
    ) -> HTTPResponse:
        """Stream download a large file with progress tracking"""

        url = self._build_url(endpoint)
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not self._session or self._session.closed:
            await self.start_session()
        
        start_time = monotonic()
        downloaded = 0
        
        async with self._session.get(url, **kwargs) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            
            with open(file_path, 'wb') as f:
                async for chunk in response.content.iter_chunked(chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if self.download_progress_callback and total_size > 0:
                        elapsed = monotonic() - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        percentage = (downloaded / total_size) * 100
                        
                        progress = DownloadProgress(
                            downloaded = downloaded,
                            total = total_size,
                            percentage = percentage,
                            speed = speed,
                            filename = file_path.name
                        )
                        self.download_progress_callback(progress)
            
            elapsed = monotonic() - start_time

            return HTTPResponse(
                status = response.status,
                headers = dict(response.headers),
                data = f"Downloaded {downloaded} bytes to {file_path}",
                elapsed = elapsed,
                url = str(response.url)
            )