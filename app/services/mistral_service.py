from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session


ENRICHED_FIELDS = (
    "date_payment",
    "from_person",
    "from_person_id",
    "whom_person",
    "whom_person_id",
    "value",
    "type_operation",
    "method_pay",
    "method_pay_id",
    "category",
    "category_id",
    "coment",
    "object",
    "object_id",
    "financial_source",
    "financial_source_id",
)


class MistralOperationDraftService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.model = os.getenv("MISTRAL_MODEL", "pixtral-12b-latest")
        self.default_from_person_id = os.getenv("OPERATIONS_DEFAULT_FROM_PERSON_ID")

    async def create_operation_draft(
        self,
        *,
        prompt: str | None,
        file_name: str | None,
        content_type: str | None,
        file_bytes: bytes | None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("Не задан MISTRAL_API_KEY")

        context = self._load_context()
        messages = self._build_messages(
            prompt=prompt,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
            context=context,
        )

        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return self._normalize_operation(self._parse_json(content))

    def _build_messages(
        self,
        *,
        prompt: str | None,
        file_name: str | None,
        content_type: str | None,
        file_bytes: bytes | None,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        system_prompt = f"""
Ты анализируешь чек, банковскую выписку, фото или текст и заполняешь черновик операции.
Верни только валидный JSON-объект без markdown и пояснений.
Схема ответа строго такая:
{{
  "date_payment": "YYYY-MM-DD",
  "from_person": "текстовое имя или null",
  "from_person_id": "uuid|null",
  "whom_person": "текстовое имя или null",
  "whom_person_id": "uuid|null",
  "value": 0.0,
  "type_operation": "entrance|expenditure",
  "method_pay": "текстовое название или null",
  "method_pay_id": 0,
  "category": "текстовое название или null",
  "category_id": "uuid|null",
  "coment": "string|null",
  "object": "текстовое название или null",
  "object_id": "uuid|null",
  "financial_source": "текстовое название или null",
  "financial_source_id": "uuid|null"
}}

Правила:
- Если это покупка/оплата/перевод кому-то, type_operation = "expenditure".
- Если это поступление денег, type_operation = "entrance".
- from_person_id по умолчанию: {self.default_from_person_id}.
- Если в справочнике есть похожее значение, заполни id и рядом текстовое поле.
- Если похожего значения в БД нет, id ставь null, а текстовое поле заполни своими словами.
- method_pay_id выбирай из методов оплаты по смыслу банка/наличных/перевода.
- whom_person_id выбирай из persons по ФИО/названию, если есть уверенное совпадение.
- category_id выбирай из категорий по смыслу операции; если нет, category напиши словами.
- object_id выбирай из объектов по названию, если пользователь указал объект; если нет, object словами.
- financial_source_id выбирай из источников финансирования по банку/счёту/смыслу.
- Не придумывай UUID или числовые id, используй только id из справочников.
- value возвращай числом JSON с точкой, например 988.58.
- coment сделай коротким: что произошло, кому/где, номер/банк/файл если полезно.

Доступные справочники:
{json.dumps(context, ensure_ascii=False, default=str)}
""".strip()

        user_text = prompt or ""
        if file_name:
            user_text = f"{user_text}\nФайл: {file_name}".strip()

        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if file_bytes and content_type and content_type.startswith("image/"):
            encoded = base64.b64encode(file_bytes).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": f"data:{content_type};base64,{encoded}",
                }
            )
        elif file_bytes:
            decoded = self._extract_file_text(
                file_bytes=file_bytes,
                content_type=content_type,
                file_name=file_name,
            )
            if decoded:
                content[0]["text"] += f"\n\nСодержимое файла:\n{decoded[:12000]}"
            else:
                content[0][
                    "text"
                ] += "\n\nФайл приложен, но не является текстом или изображением."

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

    def _load_context(self) -> dict[str, Any]:
        return {
            "default_from_person_id": self.default_from_person_id,
            "persons": self._fetch_rows(
                "SELECT id, name, surname, patronymic FROM persons ORDER BY surname, name LIMIT 300"
            ),
            "categories": self._fetch_rows(
                "SELECT id, name FROM category ORDER BY name LIMIT 300"
            ),
            "methods": self._fetch_rows(
                "SELECT id, name FROM method ORDER BY id LIMIT 100"
            ),
            "objects": self._fetch_rows(
                "SELECT id, name, object_id FROM objects ORDER BY name LIMIT 300"
            ),
            "financial_sources": self._fetch_rows(
                "SELECT id, name FROM financial_sources ORDER BY name LIMIT 300"
            ),
            "operation_types": ["entrance", "expenditure"],
        }

    def _fetch_rows(self, query: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.execute(text(query)).mappings().all()]

    @staticmethod
    def _decode_text_file(file_bytes: bytes) -> str | None:
        for encoding in ("utf-8", "cp1251"):
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    def _extract_file_text(
        self,
        *,
        file_bytes: bytes,
        content_type: str | None,
        file_name: str | None,
    ) -> str | None:
        if self._is_pdf(content_type, file_name):
            return self._extract_pdf_text(file_bytes)
        return self._decode_text_file(file_bytes)

    @staticmethod
    def _is_pdf(content_type: str | None, file_name: str | None) -> bool:
        return content_type == "application/pdf" or bool(
            file_name and file_name.lower().endswith(".pdf")
        )

    @staticmethod
    def _extract_pdf_text(file_bytes: bytes) -> str | None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
                pdf_file.write(file_bytes)
                pdf_file.flush()
                result = subprocess.run(
                    ["pdftotext", "-layout", pdf_file.name, "-"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        text_value = result.stdout.strip()
        return text_value or None

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.S)
            if not match:
                raise ValueError("Mistral не вернул JSON")
            return json.loads(match.group(0))

    def _normalize_operation(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {field: data.get(field) for field in ENRICHED_FIELDS}
        if result["from_person_id"] is None and self.default_from_person_id:
            result["from_person_id"] = self.default_from_person_id
        result["operation_payload"] = {
            "date_payment": result["date_payment"],
            "from_person": result["from_person_id"],
            "whom_person": result["whom_person_id"],
            "value": result["value"],
            "type_operation": result["type_operation"],
            "method_pay": result["method_pay_id"],
            "category_id": result["category_id"],
            "coment": result["coment"],
            "object_id": result["object_id"],
            "financial_source_id": result["financial_source_id"],
        }
        if isinstance(result["value"], str):
            result["value"] = float(result["value"].replace(",", "."))
            result["operation_payload"]["value"] = result["value"]
        if result["method_pay_id"] is not None:
            result["method_pay_id"] = int(result["method_pay_id"])
            result["operation_payload"]["method_pay"] = result["method_pay_id"]
        return result
