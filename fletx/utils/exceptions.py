"""
FletX Exceptions 
These exceptions provide better error handling and user feedback.
"""

####
##      BASE EXCEPTION CLASS
#####
class FletXError(Exception):
    """Base exception for FletX"""

    pass


####
##      ROUTE NOT FOUND EXCEPTION CLASS
#####
class RouteNotFoundError(FletXError):
    """Exception raised when a route is not found"""

    pass


####
##      NAVIGATION EXCEPTION CLASS
#####
class NavigationError(FletXError):
    """Exception raised on navigation errors"""

    pass


####
##      NAVIGATION ABORTED EXCEPTION CLASS
#####
class NavigationAborted(FletXError):
    """Exception raised when navigation is cancelled"""

    pass


####
##      DEPENDENCY NOT FOUND EXCEPTION CLASS
#####
class DependencyNotFoundError(FletXError):
    """Exception raised when a dependency is not found"""

    pass


####
##      CONTROLLER EXCEPTION CLASS
#####
class ControllerError(FletXError):
    """Exception related to controllers"""

    pass


####
##      STATE EXCEPTION CLASS
#####
class StateError(FletXError):
    """Exception related to state management"""

    pass


####
##      VALIDATION EXCEPTION CLASS
#####
class ValidationError(FletXError):
    """
    Exception raised when validation fails.
    This is used for input validation errors.
    """
    pass


####
##      CONFIGURATION EXCEPTION CLASS
#####
class ConfigurationError(FletXError):
    """
    Exception raised when there's an error with configuration.
    This includes missing config files, invalid config format, etc.
    """
    pass



####
##      BASE CLI EXCEPTION CLASS
#####
class FletXCLIError(FletXError):
    """Base class for all errors related to the Breeze CLI."""

    pass


####
##      COMMAND EXCEPTION CLASS
#####
class CommandError(FletXCLIError):
    """
    Exception raised when there's an error with command arguments or setup.
    This is typically used for user input errors or configuration issues.
    """

    def __init__(self, *args, returncode=1, **kwargs):
        self.returncode = returncode
        super().__init__(*args, **kwargs)


####
##      COMMAND NOT FOUND EXCEPTION CLASS
#####
class CommandNotFoundError(CommandError):
    """
    Exception raised when a requested command is not found in the registry.
    """

    pass
        

####
##      COMMAND EXECUTION ERROR CLASS
#####
class CommandExecutionError(CommandError):
    """
    Exception raised when a command fails during execution.
    This is used for runtime errors that occur while the command is running.
    """
    
    pass


####
##      TEMPLATE ERROR CLASS
#####
class TemplateError(FletXCLIError):
    """
    Exception raised when there's an error with template processing.
    This includes template not found, invalid template format, etc.
    """
    pass


####
##      PROJECT ERROR CLASS
#####
class ProjectError(FletXCLIError):
    """
    Exception raised when there's an error with project operations.
    This includes project not found, invalid project structure, etc.
    """
    pass


####
##      NETWORK ERROE CLASS
#####
class NetworkError(FletXError):
    """
    Exception raised when there's a network error with http operations.
    """
    def __init__(self, message=None, original_exception=None):
        self.message = message
        self.original_exception = original_exception
        super().__init__(self.message or "NetworkError:")



####
##      RATELIMOT ERROR CLASS
#####
class RateLimitError(FletXError):
    """
    Exception raised when there's a rate limit error with http operations.
    """
    def __init__(self, message=None, status_code=None, raw_response=None, headers=None):
        self.message = message
        self.status_code = status_code
        self.raw_response = raw_response
        self.headers = headers
        super().__init__(self.message or "RateLimitError:")


####
##      API ERROR CLASS
#####
class APIError(FletXError):
    """
    Exception raised when there's an API error with http operations.
    """
    def __init__(self, message=None, status_code=None, response_data=None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message or "APIError:")
