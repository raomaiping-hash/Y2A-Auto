"""
bilibili_api.exceptions.NetworkException

网络错误。
"""

from .ApiException import ApiException


class NetworkException(ApiException):
    """
    网络错误。
    """

    def __init__(self, status: int, msg: str, raw=None):
        """

        Args:
            status (int):   状态码。

            msg (str):      状态消息。

            raw (object, optional): 响应体（用于携带服务端返回的业务错误信息，如“上传过快”）。
        """
        super().__init__(msg)
        self.status = status
        self.raw = raw
        self.msg = f"网络错误，状态码：{status} - {msg}。"

    def __str__(self):
        return self.msg
