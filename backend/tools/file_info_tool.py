from __future__ import annotations

from pathlib import Path

from backend.schemas.agent_response import AgentResponse


class FileInfoTool:
    name = "file_info_tool"

    def run(self, file_path: str, user_message: str = "") -> AgentResponse:
        path = Path(str(file_path or ""))
        if not path.exists() or not path.is_file():
            return AgentResponse(
                success=False,
                route="tool",
                tool_used=True,
                tool_name=self.name,
                error_message="没有找到可读取的当前文件。",
            )
        stat = path.stat()
        suffix = path.suffix.lower() or "无扩展名"
        size = stat.st_size
        reply = "\n".join(
            [
                "这个文件的基础信息如下：",
                "",
                f"- 文件名：`{path.name}`",
                f"- 扩展名：`{suffix}`",
                f"- 文件大小：{size} bytes",
                "",
                "这只是轻量元数据读取，没有执行完整文件分析。",
            ]
        )
        return AgentResponse(
            success=True,
            reply=reply,
            intent="file_info",
            route="tool",
            tool_used=True,
            tool_name=self.name,
            data={"filename": path.name, "suffix": suffix, "size": size, "message": user_message},
            source="tool_execution",
        )
