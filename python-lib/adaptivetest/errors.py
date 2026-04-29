class AdaptiveError(Exception):
    def __init__(self, message, http_status=None, method=None):
        super(AdaptiveError, self).__init__(message)
        self.message = message
        self.http_status = http_status
        self.method = method

    def __str__(self):
        prefix = "[{}] ".format(self.method) if self.method else ""
        suffix = " (HTTP {})".format(self.http_status) if self.http_status else ""
        return "{}{}{}".format(prefix, self.message, suffix)
