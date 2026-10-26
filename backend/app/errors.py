class CategoryOSError(Exception):
    pass


class UnknownVendor(CategoryOSError):
    def __init__(self, vendor_id: str) -> None:
        super().__init__(f"unknown vendor: {vendor_id!r}")
        self.vendor_id = vendor_id


class UnknownMetric(CategoryOSError):
    def __init__(self, metric: str) -> None:
        super().__init__(f"unknown metric: {metric!r}")
        self.metric = metric


class MissingInput(CategoryOSError):
    pass
