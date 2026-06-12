from __future__ import annotations

from pathlib import Path

from backend.skills.data_analysis_skill import load_table_file

from .base import BaseFileProcessor, ProcessedFile


class CsvFileProcessor(BaseFileProcessor):
    file_type = "table"
    supported_suffixes = {".csv"}

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        try:
            load_result = load_table_file(path, preview_only=False)
        except Exception as exc:
            return self.failure(path, f"CSV 文件读取失败：{exc}")
        df = load_result.df
        missing = {str(column): int(df[column].isna().sum()) for column in df.columns}
        preview = df.head(20).fillna("").to_markdown(index=False) if not df.empty else ""
        metadata = {
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "column_names": [str(column) for column in df.columns],
            "missing_values": missing,
            "encoding": load_result.encoding,
            "suffix": path.suffix.lower(),
        }
        text = "\n".join(
            [
                f"文件名：{path.name}",
                f"行数：{metadata['rows']}，列数：{metadata['columns']}",
                f"字段：{', '.join(metadata['column_names'])}",
                "预览：",
                preview,
            ]
        )
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary=f"已读取 CSV 表格，共 {metadata['rows']} 行、{metadata['columns']} 列。",
            metadata=metadata,
            preview=preview[:4000],
            chunks=self.make_chunks(text, file_id=file_id, section="table"),
        )
