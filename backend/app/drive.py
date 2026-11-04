"""Google Drive access: sign-in, folder resolution, listing and downloads.

Sign-in uses the OAuth *installed app* (Desktop client) flow with a loopback
redirect, like ``InstalledAppFlow.run_local_server`` but non-blocking: the
loopback server waits on a background thread and the authorisation URL is
returned to the browser at once. Scope is read-only. The client file and the
token stay in ``secrets/`` (never committed); the folder does not need to be
public.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import wsgiref.simple_server
import wsgiref.util
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .errors import AppError
from .files_detect import auto_select, candidate_roles, selection_notes
from .jobs import Cancelled
from .settings import Settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
SIGNIN_TIMEOUT_S = 300

# Google may report the granted scopes in another form; don't fail on that.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


# ---------------------------------------------------------------- parsing
_FOLDER_URL_RES = (
    re.compile(r"/folders/([A-Za-z0-9_-]{10,})"),
    re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})"),
)
_FILE_URL_RE = re.compile(r"/(?:file|document|spreadsheets|presentation)/d/([A-Za-z0-9_-]{10,})")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{25,}$")


def parse_query(text: str) -> dict[str, Any]:
    """Classify what the user pasted.

    Returns ``{"kind": "id", "id"}`` or ``{"kind": "path", "root", "parts"}``
    with root in ``my_drive | shared_drive | shared_with_me | id``.
    """
    q = (text or "").strip().strip("\"'")
    if not q:
        raise AppError("Paste a Google Drive folder link or a path such as My Drive/Crowd-Density-Monitoring/Code/baseline.",
                       code="drive_query_empty", status=422)

    if re.match(r"^https?://", q, re.I) or "drive.google.com" in q:
        if _FILE_URL_RE.search(q):
            raise AppError("This is a link to a file, not a folder. Paste the link of the folder that contains the recording.",
                           code="drive_not_folder", status=422)
        for rx in _FOLDER_URL_RES:
            m = rx.search(q)
            if m:
                return {"kind": "id", "id": m.group(1)}
        raise AppError("This link does not contain a Google Drive folder id.", code="drive_bad_link", status=422)

    if "/" not in q and "\\" not in q and _ID_RE.match(q):
        return {"kind": "id", "id": q}

    p = q.replace("\\", "/")
    p = re.sub(r"^/?content/drive/", "", p)  # Colab mount point (/content/drive/My Drive/...)
    parts = [s.strip() for s in p.split("/") if s.strip()]
    if not parts:
        raise AppError("The path is empty.", code="drive_query_empty", status=422)
    head = parts[0].lower().replace(" ", "")
    if head == "mydrive":
        return {"kind": "path", "root": "my_drive", "parts": parts[1:]}
    if head == "shareddrives":
        if len(parts) < 2:
            raise AppError("Add the shared drive name after 'Shared drives/'.", code="drive_bad_path", status=422)
        return {"kind": "path", "root": "shared_drive", "parts": parts[1:]}
    if head == "sharedwithme":
        if len(parts) < 2:
            raise AppError("Add the folder name after 'Shared with me/'.", code="drive_bad_path", status=422)
        return {"kind": "path", "root": "shared_with_me", "parts": parts[1:]}
    if head == ".shortcut-targets-by-id":  # Colab path of a shared folder
        if len(parts) < 2:
            raise AppError("Incomplete .shortcut-targets-by-id path.", code="drive_bad_path", status=422)
        return {"kind": "path", "root": "id", "parts": parts[1:]}
    return {"kind": "path", "root": "my_drive", "parts": parts}


def _escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


# ---------------------------------------------------------------- loopback server
class _CallbackApp:
    """Records the OAuth redirect (``/?code=...`` or ``/?error=...``)."""

    def __init__(self) -> None:
        self.last_request_uri: str | None = None

    def __call__(self, environ, start_response):
        query = environ.get("QUERY_STRING", "")
        if "code=" not in query and "error=" not in query:
            start_response("404 Not Found", [("Content-type", "text/plain; charset=utf-8")])
            return [b"Not found"]
        self.last_request_uri = wsgiref.util.request_uri(environ)
        ok = "code=" in query
        start_response("200 OK", [("Content-type", "text/html; charset=utf-8")])
        msg = ("Signed in to Google Drive. You can close this tab and go back to the Crowd Monitoring app."
               if ok else "Google sign-in was cancelled. You can close this tab.")
        return [f"<html><body style='font-family:sans-serif;padding:40px;color:#1B2A4A'>{msg}</body></html>".encode()]


class _QuietHandler(wsgiref.simple_server.WSGIRequestHandler):
    timeout = 10  # don't hang on idle pre-connections

    def log_message(self, *args):  # silence stderr logging
        pass


class _Server(wsgiref.simple_server.WSGIServer):
    allow_reuse_address = False


# ---------------------------------------------------------------- service
class DriveService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._creds = None
        self._account: dict[str, str] | None = None
        self._signin: dict[str, Any] = {"state": "idle"}

    # ----------------------------------------------------------- client file
    def client_config(self) -> tuple[bool, str]:
        path = self.settings.google_client_secrets
        if not path.is_file():
            return False, (f"OAuth client file not found at {self._display(path)}. "
                           "Follow 'Google Drive setup' in the README.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False, f"{self._display(path)} is not a valid JSON file."
        if "installed" in data:
            return True, ""
        if "web" in data:
            return False, ("The OAuth client is a 'Web application' client. Create a 'Desktop app' "
                           "client instead (README → Google Drive setup).")
        return False, f"{self._display(path)} is not an OAuth client file."

    @staticmethod
    def _display(path: Path) -> str:
        from .settings import REPO_ROOT
        try:
            return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            return str(path)

    # ----------------------------------------------------------- credentials
    def _save_token(self, creds) -> None:
        tok = self.settings.google_token_file
        tok.parent.mkdir(parents=True, exist_ok=True)
        tok.write_text(creds.to_json(), encoding="utf-8")

    def _drop_token(self) -> None:
        self._creds = None
        self._account = None
        try:
            self.settings.google_token_file.unlink()
        except FileNotFoundError:
            pass

    def credentials(self):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        with self._lock:
            creds = self._creds
            tok = self.settings.google_token_file
            if creds is None and tok.is_file():
                try:
                    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
                except (ValueError, OSError):
                    self._drop_token()
                    creds = None
            if creds is None:
                raise AppError("Not signed in to Google Drive. Click 'Sign in with Google' first.",
                               code="drive_not_signed_in", status=401)
            if not creds.valid:
                if creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except RefreshError:
                        self._drop_token()
                        raise AppError("Your Google sign-in has expired. Please sign in again.",
                                       code="drive_not_signed_in", status=401) from None
                    except Exception as e:
                        raise AppError(f"Could not reach Google to refresh the sign-in: {e}",
                                       code="drive_network", status=502) from None
                    self._save_token(creds)
                else:
                    self._drop_token()
                    raise AppError("Your Google sign-in has expired. Please sign in again.",
                                   code="drive_not_signed_in", status=401)
            self._creds = creds
            return creds

    def _service(self):
        from googleapiclient.discovery import build

        return build("drive", "v3", credentials=self.credentials(), cache_discovery=False)

    def _account_info(self) -> dict[str, str] | None:
        if self._account is None:
            try:
                about = self._service().about().get(fields="user(displayName,emailAddress)").execute()
                user = about.get("user", {})
                self._account = {"email": user.get("emailAddress", ""), "name": user.get("displayName", "")}
            except AppError:
                raise
            except Exception as e:
                log.warning("Drive about.get failed: %s", e)
                return None
        return self._account

    # ----------------------------------------------------------- status / sign-in
    def status(self) -> dict[str, Any]:
        ok, msg = self.client_config()
        out: dict[str, Any] = {
            "client_configured": ok,
            "client_message": msg,
            "client_file": self._display(self.settings.google_client_secrets),
            "signed_in": False,
            "account": None,
            "signin": {k: v for k, v in self._signin.items() if k != "thread"},
        }
        if self.settings.google_token_file.is_file() or self._creds is not None:
            try:
                self.credentials()
                out["signed_in"] = True
                out["account"] = self._account_info()
            except AppError as e:
                out["signin"] = {"state": "error", "error": e.message}
        return out

    def start_signin(self) -> dict[str, Any]:
        from google_auth_oauthlib.flow import InstalledAppFlow

        ok, msg = self.client_config()
        if not ok:
            raise AppError(msg, code="drive_not_configured", status=409)
        with self._lock:
            cur = self._signin
            if cur.get("state") == "pending" and cur.get("thread") and cur["thread"].is_alive():
                return {"auth_url": cur["auth_url"]}

            flow = InstalledAppFlow.from_client_secrets_file(str(self.settings.google_client_secrets), scopes=SCOPES)
            app = _CallbackApp()
            server = wsgiref.simple_server.make_server(
                "localhost", 0, app, server_class=_Server, handler_class=_QuietHandler
            )
            flow.redirect_uri = f"http://localhost:{server.server_port}/"
            auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
            state: dict[str, Any] = {"state": "pending", "auth_url": auth_url, "started_at": time.time()}
            thread = threading.Thread(target=self._wait_for_redirect, args=(flow, app, server, state),
                                      name="drive-signin", daemon=True)
            state["thread"] = thread
            self._signin = state
            thread.start()
        return {"auth_url": auth_url}

    def _wait_for_redirect(self, flow, app: _CallbackApp, server, state: dict[str, Any]) -> None:
        deadline = time.time() + SIGNIN_TIMEOUT_S
        try:
            while app.last_request_uri is None and time.time() < deadline:
                server.timeout = max(1.0, deadline - time.time())
                server.handle_request()
            if app.last_request_uri is None:
                state.update(state="error", error="Google sign-in timed out. Click 'Sign in with Google' to try again.")
                return
            params = parse_qs(urlparse(app.last_request_uri).query)
            if "error" in params:
                state.update(state="error", error=f"Google sign-in was not completed ({params['error'][0]}).")
                return
            # oauthlib insists on https; the loopback redirect is plain http.
            flow.fetch_token(authorization_response=app.last_request_uri.replace("http", "https", 1))
            with self._lock:
                self._creds = flow.credentials
                self._account = None
                self._save_token(flow.credentials)
            state.update(state="done")
        except Exception as e:
            log.exception("Google sign-in failed")
            state.update(state="error", error=f"Google sign-in failed: {e}")
        finally:
            server.server_close()

    def signout(self) -> None:
        with self._lock:
            self._drop_token()
            self._signin = {"state": "idle"}

    # ----------------------------------------------------------- folders
    def _list(self, svc, q: str, fields: str, **kw) -> list[dict[str, Any]]:
        from googleapiclient.errors import HttpError

        items, token = [], None
        while True:
            try:
                resp = svc.files().list(
                    q=q, fields=f"nextPageToken, files({fields})", pageSize=1000, pageToken=token,
                    supportsAllDrives=True, includeItemsFromAllDrives=True, **kw,
                ).execute()
            except HttpError as e:
                raise self._http_error(e) from None
            items.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return items

    @staticmethod
    def _http_error(e) -> AppError:
        status = getattr(getattr(e, "resp", None), "status", 0)
        reason = ""
        try:
            reason = json.loads(e.content.decode())["error"]["message"]
        except Exception:
            reason = str(e)
        if status == 404:
            return AppError("Folder not found, or your Google account has no access to it.",
                            code="drive_not_found", status=404)
        if status in (401, 403):
            return AppError(f"Google Drive refused access: {reason}", code="drive_forbidden", status=403)
        return AppError(f"Google Drive error ({status}): {reason}", code="drive_error", status=502)

    def _get(self, svc, file_id: str, fields: str) -> dict[str, Any]:
        from googleapiclient.errors import HttpError

        try:
            return svc.files().get(fileId=file_id, fields=fields, supportsAllDrives=True).execute()
        except HttpError as e:
            raise self._http_error(e) from None

    def _as_folder(self, svc, meta: dict[str, Any]) -> dict[str, Any]:
        if meta.get("mimeType") == SHORTCUT_MIME:
            sd = meta.get("shortcutDetails", {})
            if sd.get("targetMimeType") != FOLDER_MIME:
                raise AppError(f"'{meta.get('name')}' is a shortcut to a file, not to a folder.",
                               code="drive_not_folder", status=422)
            meta = self._get(svc, sd["targetId"], "id, name, mimeType, driveId")
        if meta.get("mimeType") != FOLDER_MIME:
            raise AppError(f"'{meta.get('name')}' is a file, not a folder.", code="drive_not_folder", status=422)
        return meta

    def _child_folder(self, svc, parent_id: str, name: str, where: str) -> dict[str, Any]:
        q = (f"'{parent_id}' in parents and trashed = false and "
             f"(mimeType = '{FOLDER_MIME}' or mimeType = '{SHORTCUT_MIME}')")
        kids = self._list(svc, q, "id, name, mimeType, shortcutDetails")
        exact = [k for k in kids if k["name"] == name] or [k for k in kids if k["name"].casefold() == name.casefold()]
        for k in exact:
            try:
                return self._as_folder(svc, k)
            except AppError:
                continue
        avail = sorted(k["name"] for k in kids if k.get("mimeType") == FOLDER_MIME)[:12]
        hint = f" Folders there: {', '.join(avail)}." if avail else " It has no subfolders."
        raise AppError(f"Folder '{name}' not found in '{where}'.{hint}", code="drive_not_found", status=404)

    def _resolve(self, svc, parsed: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if parsed["kind"] == "id":
            folder = self._as_folder(svc, self._get(svc, parsed["id"], "id, name, mimeType, driveId, shortcutDetails"))
            return folder, folder["name"]

        root, parts = parsed["root"], list(parsed["parts"])
        if root == "my_drive":
            current = self._get(svc, "root", "id, name, mimeType")
            path = "My Drive"
        elif root == "id":
            current = self._as_folder(svc, self._get(svc, parts.pop(0), "id, name, mimeType, driveId, shortcutDetails"))
            path = current["name"]
        elif root == "shared_drive":
            name = parts.pop(0)
            try:
                drives = svc.drives().list(q=f"name = '{_escape(name)}'", pageSize=10).execute().get("drives", [])
            except Exception as e:
                raise AppError(f"Could not list shared drives: {e}", code="drive_error", status=502) from None
            if not drives:
                raise AppError(f"Shared drive '{name}' not found.", code="drive_not_found", status=404)
            current = {"id": drives[0]["id"], "name": drives[0]["name"], "mimeType": FOLDER_MIME}
            path = f"Shared drives/{drives[0]['name']}"
        else:  # shared_with_me
            name = parts.pop(0)
            q = (f"sharedWithMe = true and trashed = false and name = '{_escape(name)}' "
                 f"and mimeType = '{FOLDER_MIME}'")
            hits = self._list(svc, q, "id, name, mimeType")
            if not hits:
                raise AppError(f"No folder named '{name}' is shared with you.", code="drive_not_found", status=404)
            current = hits[0]
            path = f"Shared with me/{current['name']}"

        for seg in parts:
            current = self._child_folder(svc, current["id"], seg, path)
            path = f"{path}/{current['name']}"
        return current, path

    def resolve_folder(self, query: str) -> dict[str, Any]:
        """Resolve a link / id / path, list its files and pick the inputs."""
        parsed = parse_query(query)
        svc = self._service()
        folder, path = self._resolve(svc, parsed)

        items = self._list(svc, f"'{folder['id']}' in parents and trashed = false",
                           "id, name, mimeType, size, modifiedTime, shortcutDetails")
        files, folders = [], []
        for it in items:
            mime = it.get("mimeType", "")
            if mime == FOLDER_MIME or (mime == SHORTCUT_MIME and
                                       it.get("shortcutDetails", {}).get("targetMimeType") == FOLDER_MIME):
                folders.append({"id": it["id"], "name": it["name"]})
                continue
            download_id, size = it["id"], it.get("size")
            if mime == SHORTCUT_MIME:
                target = it.get("shortcutDetails", {}).get("targetId")
                if not target:
                    continue
                try:
                    meta = self._get(svc, target, "id, size, mimeType")
                except AppError:
                    continue
                download_id, size, mime = meta["id"], meta.get("size"), meta.get("mimeType", "")
            downloadable = size is not None and not mime.startswith("application/vnd.google-apps.")
            files.append({
                "id": download_id,
                "name": it["name"],
                "size": int(size) if size is not None else None,
                "mime_type": mime,
                "modified_time": it.get("modifiedTime"),
                "candidate_roles": candidate_roles(it["name"]) if downloadable else [],
            })
        files.sort(key=lambda f: f["name"].lower())
        folders.sort(key=lambda f: f["name"].lower())

        selectable = [f for f in files if f["candidate_roles"]]
        selection = auto_select(selectable)
        return {
            "folder": {"id": folder["id"], "name": folder["name"], "path": path},
            "files": files,
            "subfolders": folders,
            "selection": selection,
            "notes": selection_notes(selectable, selection),
        }

    # ----------------------------------------------------------- download
    def download(
        self,
        file_id: str,
        dest: Path,
        expected_size: int | None,
        on_progress: Callable[[int], None],
        cancel_event: threading.Event,
        display_name: str,
    ) -> None:
        """Stream a file to ``dest`` (via ``dest.part``), resuming after errors.

        ``on_progress`` receives the number of bytes of this file on disk.
        """
        import requests
        from google.auth.transport.requests import AuthorizedSession

        session = AuthorizedSession(self.credentials())
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        part = dest.with_name(dest.name + ".part")
        failures = 0
        while True:
            have = part.stat().st_size if part.exists() else 0
            if expected_size is not None and have > expected_size:
                part.unlink()
                have = 0
            if expected_size is not None and have == expected_size:
                break
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                with session.get(url, params={"alt": "media", "supportsAllDrives": "true"},
                                 headers=headers, stream=True, timeout=(15, 120)) as r:
                    if r.status_code == 416 and have:
                        break  # nothing left to fetch
                    if r.status_code >= 400:
                        raise self._download_error(r, display_name)
                    if have and r.status_code != 206:
                        have = 0  # server ignored the Range header: start over
                    with open(part, "ab" if have else "wb") as fh:
                        written = have
                        for chunk in r.iter_content(chunk_size=1 << 20):
                            if cancel_event.is_set():
                                raise Cancelled()
                            if chunk:
                                fh.write(chunk)
                                written += len(chunk)
                                on_progress(written)
                if expected_size is None:
                    break
            except (requests.ConnectionError, requests.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                failures += 1
                if failures > 5:
                    raise AppError(f"Download of {display_name} failed after several retries: {e}",
                                   code="drive_download_failed", status=502) from None
                log.warning("Download of %s interrupted (%s); retrying", display_name, e)
                for _ in range(int(min(2 ** failures, 20) * 10)):
                    if cancel_event.is_set():
                        raise Cancelled() from None
                    time.sleep(0.1)
        size = part.stat().st_size if part.exists() else 0
        if expected_size is not None and size != expected_size:
            raise AppError(f"{display_name}: downloaded {size} bytes, expected {expected_size}.",
                           code="drive_download_failed", status=502)
        os.replace(part, dest)

    @staticmethod
    def _download_error(r, name: str) -> AppError:
        reason, message = "", r.text[:300]
        try:
            err = r.json()["error"]
            message = err.get("message", message)
            reason = (err.get("errors") or [{}])[0].get("reason", "")
        except Exception:
            pass
        if r.status_code == 404:
            return AppError(f"{name} no longer exists on Google Drive, or you lost access to it.",
                            code="drive_not_found", status=404)
        if reason == "downloadQuotaExceeded":
            return AppError(f"Google Drive's download quota for {name} is exceeded. Try again later.",
                            code="drive_quota", status=429)
        if reason == "cannotDownloadAbusiveFile":
            return AppError(f"Google Drive flagged {name} and blocks its download.",
                            code="drive_forbidden", status=403)
        return AppError(f"Downloading {name} failed ({r.status_code}): {message}",
                        code="drive_download_failed", status=502)
