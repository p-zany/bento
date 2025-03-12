"""
Password handling module for encrypted files.
"""

import os
import tempfile
import zipfile
from typing import Any, Awaitable, Callable, Dict, Optional

import magic
import pikepdf
import py7zr
import rarfile
from loguru import logger


class FilePasswordHandler:
    def __init__(self):
        self.mime = magic.Magic(mime=True)

    async def process_file(
        self,
        file_path: str,
        mime_type: Optional[Any] = None,
        password_callback: Callable[[str], Awaitable[str]] = None,
        topic: str = "",
    ) -> Optional[bytes]:
        if mime_type is None:
            detected_mime = self.__detect_mime_type(file_path)
        else:
            detected_mime = getattr(mime_type, "value", str(mime_type))

        if password_callback:
            password = await password_callback(topic)
            if not password:
                logger.warning(f"No password provided for {topic}")
                return None
        else:
            password = ""

        if "pdf" in detected_mime.lower():
            return await self.__decrypt_pdf(file_path, password)

        elif any(x in detected_mime.lower() for x in ["zip", "rar", "7z"]):
            files = await self.__extract_archive(file_path, password, detected_mime)
            if files:
                return next(iter(files.values()), None)
        else:
            try:
                with open(file_path, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Error reading file {file_path}: {e}")

        logger.warning(f"Failed to process file with mime type: {detected_mime}")
        return None

    def __detect_mime_type(self, file_path: str) -> str:
        return self.mime.from_file(file_path)

    async def __decrypt_pdf(self, file_path: str, password: str) -> Optional[bytes]:
        try:
            with pikepdf.open(file_path, password=password) as pdf:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    pdf.save(tmp.name)

                with open(tmp.name, "rb") as f:
                    content = f.read()

                os.unlink(tmp.name)
                logger.debug(f"Successfully decrypted PDF: {file_path}")
                return content

        except pikepdf.PasswordError:
            logger.warning(f"Invalid password for PDF: {file_path}")
            return None
        except Exception as e:
            logger.error(f"Error decrypting PDF {file_path}: {e}")
            return None

    async def __extract_archive(
        self, file_path: str, password: str, mime_type: Optional[str] = None
    ) -> Optional[Dict[str, bytes]]:
        detected_mime = mime_type or self.__detect_mime_type(file_path)

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                if "zip" in detected_mime:
                    with zipfile.ZipFile(file_path) as zip_file:
                        if zip_file.testzip() is not None:
                            zip_file.extractall(path=tmp_dir, pwd=password.encode())
                        else:
                            zip_file.extractall(path=tmp_dir)

                elif "rar" in detected_mime:
                    with rarfile.RarFile(file_path) as rar_file:
                        if rar_file.needs_password():
                            rar_file.extractall(path=tmp_dir, pwd=password)
                        else:
                            rar_file.extractall(path=tmp_dir)

                elif "7z" in detected_mime:
                    with py7zr.SevenZipFile(
                        file_path, mode="r", password=password
                    ) as z:
                        z.extractall(path=tmp_dir)
                else:
                    logger.warning(f"Unsupported archive type: {detected_mime}")
                    return None

                files = {}
                for root, _, filenames in os.walk(tmp_dir):
                    for filename in filenames:
                        file_path = os.path.join(root, filename)
                        relative_path = os.path.relpath(file_path, tmp_dir)
                        with open(file_path, "rb") as f:
                            files[relative_path] = f.read()

                logger.debug(f"Successfully extracted archive: {file_path}")
                return files

        except (zipfile.BadZipFile, rarfile.BadRarFile, py7zr.Bad7zFile) as e:
            logger.warning(f"Invalid archive or password: {file_path}, error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting archive {file_path}: {e}")
            return None
