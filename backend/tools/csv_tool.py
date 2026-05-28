from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backend.schemas.agent_response import AgentResponse
from backend.skills.data_analysis_skill import load_table_file


class CsvTool:
    name = "csv_tool"

    def run(self, file_path: str, user_message: str = "") -> AgentResponse:
        if not file_path:
            return AgentResponse(success=False, error_message="没有提供 CSV/Excel 文件路径。", tool_used=True, tool_name=self.name)
        df = load_table_file(Path(file_path), preview_only=False).df
        row_count = int(len(df))
        column_names = [str(column) for column in df.columns]
        missing_rows = [
            {"column": str(column), "missing_count": int(df[column].isna().sum())}
            for column in df.columns
            if int(df[column].isna().sum()) > 0
        ]
        numeric_df = df.select_dtypes(include=["number"])
        numeric_summary = (
            numeric_df.describe().transpose()[["count", "mean", "min", "max"]].round(4).reset_index().rename(columns={"index": "column"})
            if not numeric_df.empty
            else pd.DataFrame()
        )
        preview = df.head(20).fillna("").astype(object).to_dict(orient="records")
        markdown_lines = [
            f"该表格共有 **{row_count}** 行、**{len(column_names)}** 列。",
            f"列名：{('、'.join(column_names) if column_names else '无')}",
        ]
        if missing_rows:
            markdown_lines.append("\n缺失值统计：")
            markdown_lines.append(self._markdown_table(["列名", "空值数"], [[row["column"], row["missing_count"]] for row in missing_rows]))
        else:
            markdown_lines.append("\n当前表格没有检测到缺失值。")
        if not numeric_summary.empty:
            markdown_lines.append("\n数值列基础统计：")
            markdown_lines.append(
                self._markdown_table(
                    ["列名", "count", "mean", "min", "max"],
                    numeric_summary[["column", "count", "mean", "min", "max"]].values.tolist(),
                )
            )
        reply = "\n\n".join(markdown_lines)
        return AgentResponse(
            success=True,
            reply=reply,
            tool_used=True,
            tool_name=self.name,
            data={
                "row_count": row_count,
                "column_count": len(column_names),
                "column_names": column_names,
                "missing_values": missing_rows,
                "numeric_summary": numeric_summary.to_dict(orient="records") if not numeric_summary.empty else [],
                "preview": preview,
            },
            debug={"tool": self.name, "message": user_message},
            source="tool_execution",
        )

    def _markdown_table(self, headers: list[Any], rows: list[list[Any]]) -> str:
        header = "| " + " | ".join(str(item) for item in headers) + " |"
        divider = "| " + " | ".join("---" for _ in headers) + " |"
        body = ["| " + " | ".join(str("" if item is None else item) for item in row) + " |" for row in rows]
        return "\n".join([header, divider, *body])
