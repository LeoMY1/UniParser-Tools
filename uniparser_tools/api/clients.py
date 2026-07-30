import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

import requests
from PIL import Image

from uniparser_tools.api.transport import (
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SYNC_REQUEST_TIMEOUT,
    RequestTimeout,
    UniParserHTTPTransport,
)
from uniparser_tools.common.constant import (
    FormatFlag,
    IntEnum,
    Language,
    OrderingMethod,
    ParseMode,
    ParseModeTextual,
    StatusFlag,
    ThirdPartyFormatter,
)
from uniparser_tools.utils.image import dump_image_base64_str


def int_enum_factory(items):
    return {k: int(v) if isinstance(v, IntEnum) else v for k, v in items}


PresetLayout = Union[str, List[Any]]


def serialize_preset_layout(preset_layout: Optional[PresetLayout]) -> str:
    """Serialize preset layout consistently for form and JSON endpoints."""
    if preset_layout is None:
        return ""
    if isinstance(preset_layout, str):
        return preset_layout
    return json.dumps(preset_layout, ensure_ascii=False)


@dataclass
class TriggerFileData:
    token: Optional[str]
    lang: Language
    sync: bool
    textual: Union[ParseModeTextual, bool]
    table: Union[ParseMode, bool]
    molecule: Union[ParseMode, bool]
    chart: Union[ParseMode, bool]
    figure: Union[ParseMode, bool]
    expression: Union[ParseMode, bool]
    equation: Union[ParseMode, bool]
    pages: List[int] = None
    ordering_method: OrderingMethod = OrderingMethod.XYCutExp
    callback_url: str = None
    callback_secret: str = None
    timeout: int = 1800
    padding_snip: bool = True
    inplace_update: bool = False
    preset_layout: str = ""
    model_version: Optional[str] = None


@dataclass
class TriggerURLData:
    url: str
    token: Optional[str]
    lang: Language
    sync: bool
    textual: Union[ParseModeTextual, bool]
    table: Union[ParseMode, bool]
    molecule: Union[ParseMode, bool]
    chart: Union[ParseMode, bool]
    figure: Union[ParseMode, bool]
    expression: Union[ParseMode, bool]
    equation: Union[ParseMode, bool]
    pages: List[int] = None
    ordering_method: OrderingMethod = OrderingMethod.XYCutExp
    proxy: str = None
    callback_url: str = None
    callback_secret: str = None
    timeout: int = 1800
    inplace_update: bool = False
    preset_layout: str = ""
    model_version: Optional[str] = None


@dataclass
class TOSUploadFile:
    filename: str
    token: Optional[str] = None


@dataclass
class GetResultData:
    token: str
    content: bool
    objects: bool
    pages_dict: bool
    pages_tree: bool
    molecule_source: bool


@dataclass
class GetFormattedData:
    token: str
    content: bool
    objects: bool
    pages_dict: bool
    pages_tree: bool
    molecule_source: bool
    textual: FormatFlag
    table: FormatFlag
    molecule: FormatFlag
    chart: FormatFlag
    figure: FormatFlag
    expression: FormatFlag
    equation: FormatFlag
    marginalia: bool


@dataclass
class GetThirdPartyData:
    token: str
    formatter: ThirdPartyFormatter


class UniParserClient:
    def __init__(
        self,
        host: str,
        api_key: str,
        *,
        request_timeout: RequestTimeout = DEFAULT_REQUEST_TIMEOUT,
        sync_request_timeout: RequestTimeout = DEFAULT_SYNC_REQUEST_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self._transport = UniParserHTTPTransport(
            host,
            api_key,
            request_timeout=request_timeout,
            session=session,
        )
        self.api_key = api_key
        self.user = uuid.uuid5(uuid.NAMESPACE_DNS, self.api_key)
        self.host = self._transport.host
        self.request_timeout = request_timeout
        self.sync_request_timeout = sync_request_timeout

    def close(self):
        self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _trigger_http_timeout(self, sync: bool, http_timeout: Optional[RequestTimeout] = None):
        if http_timeout is not None:
            return http_timeout
        return self.sync_request_timeout if sync else self.request_timeout

    def _trigger_token(self, seed: str, token: Optional[str], server_generated_token: bool) -> Optional[str]:
        if token is None and not server_generated_token:
            token = self.to_token(seed)
        if token is not None:
            self.validate_token(token)
        return token

    @property
    def trigger_file_endpoint(self):
        return f"{self.host}/trigger-file-async"

    @property
    def trigger_url_endpoint(self):
        return f"{self.host}/trigger-url-async"

    @property
    def trigger_snip_endpoint(self):
        return f"{self.host}/trigger-snip-async"

    @property
    def request_tos_upload_links_endpoint(self):
        return f"{self.host}/request-tos-upload-links"

    @property
    def health_endpoint(self):
        return f"{self.host}/health"

    @property
    def version_endpoint(self):
        return f"{self.host}/version"

    @property
    def get_constants_endpoint(self):
        return f"{self.host}/get-constants"

    @property
    def get_result_endpoint(self):
        return f"{self.host}/get-result"

    @property
    def get_formatted_endpoint(self):
        return f"{self.host}/get-formatted"

    @property
    def get_third_party_output_endpoint(self):
        return f"{self.host}/get-third-party-output"

    def to_token(self, task_id: str):
        token = uuid.uuid5(self.user, task_id).hex
        return token

    def validate_token(self, token: str):
        assert re.match(r"^[-\._?=&a-zA-Z0-9]{1,128}$", token), f"token: {token} contains illegal characters"

    def health(self, *, http_timeout: Optional[RequestTimeout] = None):
        return self._transport.request("GET", "/health", timeout=http_timeout, error_message="health check failed")

    def version(self, *, http_timeout: Optional[RequestTimeout] = None):
        return self._transport.request("GET", "/version", timeout=http_timeout, error_message="version request failed")

    def get_constants(self, *, http_timeout: Optional[RequestTimeout] = None):
        return self._transport.request(
            "GET",
            "/get-constants",
            timeout=http_timeout,
            error_message="constants request failed",
        )

    def trigger_file(
        self,
        file_path: str,
        token: Optional[str] = None,
        lang: Language = Language.Unknown,
        sync: bool = True,
        textual: Union[ParseModeTextual, bool] = ParseModeTextual.DigitalExported,
        table: Union[ParseMode, bool] = ParseMode.Disable,
        molecule: Union[ParseMode, bool] = ParseMode.Disable,
        chart: Union[ParseMode, bool] = ParseMode.Disable,
        figure: Union[ParseMode, bool] = ParseMode.Disable,
        expression: Union[ParseMode, bool] = ParseMode.Disable,
        equation: Union[ParseMode, bool] = ParseMode.Disable,
        pages: List[int] = None,
        ordering_method: OrderingMethod = OrderingMethod.GapTree,
        callback_url: str = None,
        callback_secret: str = None,
        timeout: int = 1800,
        padding_snip: bool = True,
        inplace_update: bool = False,
        preset_layout: Optional[PresetLayout] = None,
        model_version: Optional[str] = None,
        server_generated_token: bool = False,
        http_timeout: Optional[RequestTimeout] = None,
        **kwargs,
    ):
        """
        sync: True=同步解析，该请求会在解析完成后才返回; False=异步解析，该请求会立即返回，解析结果需要通过GetResult接口获取
        timeout: 服务端解析预算（秒），与客户端 HTTP 超时 http_timeout 相互独立
        callback_url: 异步解析完成后的回调地址
        callback_secret: 回调验证密钥
        server_generated_token: token 为空时由服务端生成；默认 False 以保持历史确定性 token 行为
        """
        token = self._trigger_token(file_path, token, server_generated_token)
        trigger_data = TriggerFileData(
            token=token,
            lang=lang,
            sync=sync,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            pages=pages,
            timeout=timeout,
            ordering_method=ordering_method,
            padding_snip=padding_snip,
            inplace_update=inplace_update,
            preset_layout=serialize_preset_layout(preset_layout),
            model_version=model_version,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )

        try:
            data = asdict(trigger_data, dict_factory=int_enum_factory)
            with open(file_path, "rb") as file_obj:
                return self._transport.request(
                    "POST",
                    "/trigger-file-async",
                    files={"file": file_obj},
                    data=data,
                    timeout=self._trigger_http_timeout(sync, http_timeout),
                    error_message="trigger file failed",
                    token=token,
                )
        except OSError as exc:
            return {
                "status": StatusFlag.Error,
                "token": token,
                "message": "trigger file failed",
                "description": str(exc),
                "error_type": type(exc).__name__,
            }

    def trigger_snip(
        self,
        snip_path: str,
        token: Optional[str] = None,
        lang: Language = Language.Unknown,
        sync: bool = True,
        textual: Union[ParseModeTextual, bool] = ParseModeTextual.DigitalExported,
        table: Union[ParseMode, bool] = ParseMode.Disable,
        molecule: Union[ParseMode, bool] = ParseMode.Disable,
        chart: Union[ParseMode, bool] = ParseMode.Disable,
        figure: Union[ParseMode, bool] = ParseMode.Disable,
        expression: Union[ParseMode, bool] = ParseMode.Disable,
        equation: Union[ParseMode, bool] = ParseMode.Disable,
        pages: List[int] = None,
        ordering_method: OrderingMethod = OrderingMethod.GapTree,
        callback_url: str = None,
        callback_secret: str = None,
        timeout: int = 1800,
        padding_snip: bool = True,
        inplace_update: bool = False,
        preset_layout: Optional[PresetLayout] = None,
        model_version: Optional[str] = None,
        server_generated_token: bool = False,
        http_timeout: Optional[RequestTimeout] = None,
        **kwargs,
    ):
        token = self._trigger_token(snip_path, token, server_generated_token)
        trigger_data = TriggerFileData(
            token=token,
            lang=lang,
            sync=sync,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            pages=pages,
            timeout=timeout,
            ordering_method=ordering_method,
            padding_snip=padding_snip,
            inplace_update=inplace_update,
            preset_layout=serialize_preset_layout(preset_layout),
            model_version=model_version,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )

        try:
            with Image.open(snip_path) as source_image:
                img = dump_image_base64_str(source_image.convert("RGB"))
            data = {"img": img, **asdict(trigger_data, dict_factory=int_enum_factory)}
            return self._transport.request(
                "POST",
                "/trigger-snip-async",
                data=data,
                timeout=self._trigger_http_timeout(sync, http_timeout),
                error_message="trigger snip failed",
                token=token,
            )
        except (OSError, ValueError) as exc:
            return {
                "status": StatusFlag.Error,
                "token": token,
                "message": "trigger snip failed",
                "description": str(exc),
                "error_type": type(exc).__name__,
            }

    def trigger_url(
        self,
        pdf_url: str,
        token: Optional[str] = None,
        lang: Language = Language.Unknown,
        sync: bool = True,
        textual: Union[ParseModeTextual, bool] = ParseModeTextual.DigitalExported,
        table: Union[ParseMode, bool] = ParseMode.Disable,
        molecule: Union[ParseMode, bool] = ParseMode.Disable,
        chart: Union[ParseMode, bool] = ParseMode.Disable,
        figure: Union[ParseMode, bool] = ParseMode.Disable,
        expression: Union[ParseMode, bool] = ParseMode.Disable,
        equation: Union[ParseMode, bool] = ParseMode.Disable,
        pages: List[int] = None,
        ordering_method: OrderingMethod = OrderingMethod.GapTree,
        proxy: str = None,
        callback_url: str = None,
        callback_secret: str = None,
        timeout: int = 1800,
        inplace_update: bool = False,
        preset_layout: Optional[PresetLayout] = None,
        model_version: Optional[str] = None,
        server_generated_token: bool = False,
        http_timeout: Optional[RequestTimeout] = None,
        **kwargs,
    ):
        token = self._trigger_token(pdf_url, token, server_generated_token)
        trigger_data = TriggerURLData(
            url=pdf_url,
            token=token,
            lang=lang,
            sync=sync,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            pages=pages,
            timeout=timeout,
            ordering_method=ordering_method,
            proxy=proxy,
            inplace_update=inplace_update,
            preset_layout=serialize_preset_layout(preset_layout),
            model_version=model_version,
            callback_url=callback_url,
            callback_secret=callback_secret,
        )
        data = asdict(trigger_data, dict_factory=int_enum_factory)
        return self._transport.request(
            "POST",
            "/trigger-url-async",
            json=data,
            timeout=self._trigger_http_timeout(sync, http_timeout),
            error_message="trigger url failed",
            token=token,
        )

    def request_tos_upload_links(
        self,
        files: Sequence[Union[str, TOSUploadFile, Dict[str, Optional[str]]]],
        *,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        """Request authenticated, presigned TOS upload targets.

        ``files`` may contain filenames, ``TOSUploadFile`` instances, or
        dictionaries with ``filename`` and optional ``token`` fields.
        """
        normalized_files = []
        for item in files:
            if isinstance(item, str):
                upload_file = TOSUploadFile(filename=item)
            elif isinstance(item, TOSUploadFile):
                upload_file = item
            elif isinstance(item, dict):
                upload_file = TOSUploadFile(filename=item.get("filename", ""), token=item.get("token"))
            else:
                return {
                    "status": StatusFlag.Error,
                    "message": "request TOS upload links failed",
                    "description": f"unsupported file descriptor: {type(item).__name__}",
                }
            normalized_files.append(asdict(upload_file))

        return self._transport.request(
            "POST",
            "/request-tos-upload-links",
            json={"files": normalized_files},
            timeout=http_timeout,
            error_message="request TOS upload links failed",
        )

    def upload_files_to_tos(
        self,
        file_paths: Sequence[str],
        *,
        tokens: Optional[Sequence[Optional[str]]] = None,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        """Upload local PDF/image files to TOS and return their ``source_url`` values.

        This helper requests presigned URLs and performs unauthenticated ``PUT``
        uploads. It intentionally leaves parsing as a separate ``trigger_url``
        call so uploading alone never starts a billable parse.
        """
        if tokens is not None and len(tokens) != len(file_paths):
            return {
                "status": StatusFlag.Error,
                "message": "upload files to TOS failed",
                "description": "tokens and file_paths must have the same length",
            }

        upload_files = [
            TOSUploadFile(
                filename=os.path.basename(file_path),
                token=tokens[index] if tokens is not None else None,
            )
            for index, file_path in enumerate(file_paths)
        ]
        links_response = self.request_tos_upload_links(upload_files, http_timeout=http_timeout)
        if not isinstance(links_response, dict) or not isinstance(links_response.get("files"), list):
            return links_response

        links = links_response["files"]
        if len(links) != len(file_paths):
            return {
                "status": StatusFlag.Error,
                "message": "upload files to TOS failed",
                "description": "the service returned an unexpected number of upload links",
                "files": links,
            }

        uploaded_files = []
        for file_path, link in zip(file_paths, links):
            upload_url = link.get("upload_url") if isinstance(link, dict) else None
            if not upload_url:
                return {
                    "status": StatusFlag.Error,
                    "message": "upload files to TOS failed",
                    "description": "the service returned an upload target without upload_url",
                    "files": uploaded_files,
                }
            try:
                with open(file_path, "rb") as file_obj:
                    upload_result = self._transport.request(
                        "PUT",
                        upload_url,
                        authenticated=False,
                        expect_json=False,
                        data=file_obj,
                        timeout=http_timeout,
                        error_message="TOS upload failed",
                    )
            except OSError as exc:
                return {
                    "status": StatusFlag.Error,
                    "message": "upload files to TOS failed",
                    "description": str(exc),
                    "error_type": type(exc).__name__,
                    "files": uploaded_files,
                }

            if upload_result.get("status") == StatusFlag.Error:
                return {
                    "status": StatusFlag.Error,
                    "message": "upload files to TOS failed",
                    "description": f"TOS upload failed for {file_path}",
                    "upload": upload_result,
                    "files": uploaded_files,
                }
            uploaded_files.append({**link, "uploaded": True})

        return {"status": StatusFlag.Success, "files": uploaded_files}

    def get_result(
        self,
        token: str,
        content: bool = False,
        objects: bool = False,
        pages_dict: bool = False,
        pages_tree: bool = False,
        molecule_source: bool = False,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        data = GetResultData(
            token=token,
            content=content,
            objects=objects,
            pages_dict=pages_dict,
            pages_tree=pages_tree,
            molecule_source=molecule_source,
        )
        payload = asdict(data, dict_factory=int_enum_factory)
        return self._transport.request(
            "POST",
            "/get-result",
            json=payload,
            timeout=http_timeout,
            error_message="get result failed",
            token=token,
        )

    def get_formatted(
        self,
        token: str,
        content: bool = False,
        objects: bool = False,
        pages_dict: bool = False,
        pages_tree: bool = False,
        molecule_source: bool = False,
        textual: FormatFlag = FormatFlag.Markdown,
        table: FormatFlag = FormatFlag.Markdown,
        molecule: FormatFlag = FormatFlag.Markdown,
        chart: FormatFlag = FormatFlag.Markdown,
        figure: FormatFlag = FormatFlag.Markdown,
        expression: FormatFlag = FormatFlag.Markdown,
        equation: FormatFlag = FormatFlag.Markdown,
        marginalia: bool = False,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        data = GetFormattedData(
            token=token,
            content=content,
            objects=objects,
            pages_dict=pages_dict,
            pages_tree=pages_tree,
            molecule_source=molecule_source,
            textual=textual,
            table=table,
            molecule=molecule,
            chart=chart,
            figure=figure,
            expression=expression,
            equation=equation,
            marginalia=marginalia,
        )
        payload = asdict(data, dict_factory=int_enum_factory)
        return self._transport.request(
            "POST",
            "/get-formatted",
            json=payload,
            timeout=http_timeout,
            error_message="get formatted failed",
            token=token,
        )

    def get_third_party_output(
        self,
        token: str,
        formatter: ThirdPartyFormatter = ThirdPartyFormatter.MinerU,
        *,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        data = GetThirdPartyData(token=token, formatter=formatter)
        payload = asdict(data, dict_factory=int_enum_factory)
        return self._transport.request(
            "POST",
            "/get-third-party-output",
            json=payload,
            timeout=http_timeout,
            error_message="get third-party output failed",
            token=token,
        )
