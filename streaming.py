import re
import json
import urllib.parse
import urllib.request

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor

from storage import CHROME_UA


def patch_urllib3_percent_re():
    """Python 3.14 / 3.15 환경에서 urllib3 / yt-dlp 호환성 버그 자동 패치"""
    try:
        import urllib3.util.url as _u3_url
        if hasattr(_u3_url, "_PERCENT_RE") and not hasattr(_u3_url._PERCENT_RE, "sub"):
            cls = type(_u3_url._PERCENT_RE)
            if hasattr(cls, "subn") and not hasattr(cls, "sub"):
                cls.sub = lambda self, repl, string, count=0: self.subn(repl, string, count)[0]
            else:
                _u3_url._PERCENT_RE = re.compile(r"%[a-fA-F0-9]{2}")
    except Exception:
        pass
    try:
        import yt_dlp.networking._requests as _ydl_req
        if hasattr(_ydl_req, "Urllib3UtilUrlPercentReOverride"):
            ovr_cls = _ydl_req.Urllib3UtilUrlPercentReOverride
            if not hasattr(ovr_cls, "sub"):
                ovr_cls.sub = lambda self, repl, string, count=0: self.subn(repl, string, count)[0]
    except Exception:
        pass


patch_urllib3_percent_re()

try:
    import streamlink
    HAS_STREAMLINK = True
except ImportError:
    streamlink = None
    HAS_STREAMLINK = False

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    yt_dlp = None
    HAS_YTDLP = False

patch_urllib3_percent_re()


class SoopHeaderInterceptor(QWebEngineUrlRequestInterceptor):
    """SOOP 채팅 및 API 요청 시 정확한 호스트 검증 후 Referer 헤더를 주입하여 외부 차단 방지"""
    def interceptRequest(self, info):
        host = info.requestUrl().host().lower()
        if not host or host.startswith("login."):
            return
        if host == "sooplive.co.kr" or host.endswith(".sooplive.co.kr"):
            info.setHttpHeader(b"Referer", b"https://play.sooplive.co.kr/")
        elif host == "sooplive.com" or host.endswith(".sooplive.com"):
            info.setHttpHeader(b"Referer", b"https://play.sooplive.com/")
        elif host == "afreecatv.com" or host.endswith(".afreecatv.com"):
            info.setHttpHeader(b"Referer", b"https://play.afreecatv.com/")


class PopupSupportWebPage(QWebEnginePage):
    """SOOP/네이버/구글 로그인 및 채팅창 내 2차 인증 팝업 허용 (닫힘 시 메모리 자동 해제)"""
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._popups = []

    def _remove_popup(self, popup_view):
        if popup_view in self._popups:
            self._popups.remove(popup_view)
        popup_view.deleteLater()

    def createWindow(self, win_type):
        popup = QWebEngineView()
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        page = PopupSupportWebPage(self.profile(), popup)
        popup.setPage(page)
        popup.setWindowTitle("인증 / 로그인 팝업")
        popup.resize(480, 680)
        popup.show()
        self._popups.append(popup)
        page.windowCloseRequested.connect(popup.close)
        popup.destroyed.connect(lambda *_, p=popup: self._remove_popup(p) if p in self._popups else None)
        return page


# ==============================================================================
# SOOP 실시간 채팅 전용 부트스트랩 & 비파괴(Non-Destructive) 풀스크린 오버레이 스크립트
# ==============================================================================
SOOP_CHAT_DOM_MASK_JS = """
(function() {
    if (!location.hostname.includes('sooplive') && !location.hostname.includes('afreecatv')) return;
    if (location.hostname.includes('login.')) return;

    if (!window.__soopMseShimInstalled) {
        window.__soopMseShimInstalled = true;
        if (typeof window.MediaSource !== 'undefined') {
            window.MediaSource.isTypeSupported = function() { return true; };
        }
        if (typeof HTMLMediaElement !== 'undefined') {
            HTMLMediaElement.prototype.canPlayType = function() { return 'probably'; };
            const origAddEL = HTMLMediaElement.prototype.addEventListener;
            HTMLMediaElement.prototype.addEventListener = function(type, listener, options) {
                if (type === 'error') return;
                return origAddEL.call(this, type, listener, options);
            };
        }
    }

    function ensureSoopDarkMode() {
        try {
            const h = location.hostname || '';
            const cookieDomain = h.endsWith('.sooplive.co.kr') ? '.sooplive.co.kr'
                : (h.endsWith('.sooplive.com') ? '.sooplive.com' : '');
            if (cookieDomain && !document.cookie.includes('theme=dark')) {
                document.cookie = `theme=dark; path=/; domain=${cookieDomain}; max-age=31536000`;
            }
            if (document.documentElement && document.documentElement.getAttribute('dark') !== 'true') {
                document.documentElement.setAttribute('dark', 'true');
            }
        } catch (e) {}
    }

    ensureSoopDarkMode();

    const CHAT_CSS = `
        html, body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            min-width: 100vw !important;
            min-height: 100vh !important;
            overflow: hidden !important;
            background: #121216 !important;
            color: #eef2f6 !important;
        }
        #header, .header, #gnb, .gnb, .broadcast_information, #footer, footer,
        #player_info, .layer_ad, #chat_ad, .chat_banner, .chat_banner2, #sooptoreBox {
            display: none !important;
        }
        #player_area, .player_area {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 1px !important;
            height: 1px !important;
            opacity: 0.01 !important;
            pointer-events: none !important;
            z-index: -1 !important;
            overflow: hidden !important;
        }
        section.chatting_box, #chatting_area {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            max-width: 100vw !important;
            max-height: 100vh !important;
            margin: 0 !important;
            padding: 0 !important;
            z-index: 2147483640 !important;
            display: flex !important;
            flex-direction: column !important;
            visibility: visible !important;
            opacity: 1 !important;
            background: #121216 !important;
            color: #eef2f6 !important;
        }
        #chatbox {
            width: 100% !important;
            height: 100% !important;
            display: flex !important;
            flex-direction: column !important;
            background: #121216 !important;
        }
        #chatbox > .area_header,
        #chatbox .chat_title h2,
        #chatbox .chat_title span {
            background: #16161d !important;
            color: #e5e7eb !important;
            border-color: #282836 !important;
        }
        #chatbox .chatting-item-wrap {
            flex: 1 1 auto !important;
            min-height: 0 !important;
            background: #121216 !important;
        }
        #chat_area,
        #chat_area .chatting-list-item,
        #chat_area .message-container,
        #chat_area .message-text,
        #chat_area .msg,
        #chat_area p,
        .chat_scroll_down .chatting-list-item,
        .chat_scroll_down .chatting-list-item .msg {
            color: #eef2f6 !important;
        }
        #chat_area .start-message .msg,
        #chat_area .system-message {
            color: #94a3b8 !important;
        }
        #chat_write,
        #chatbox .chat_write,
        #chatbox .actionbox {
            background: #16161d !important;
            border-color: #2c2c3a !important;
        }
        #chatbox .input_chat {
            background: #1f1f29 !important;
            border: 1px solid #353548 !important;
            border-radius: 6px !important;
        }
        #write_area {
            color: #f3f4f6 !important;
            caret-color: #00e5ff !important;
        }
        #empty_chat {
            color: #8b95a5 !important;
        }
    `;

    function applySoopChatLayoutAndConnect() {
        try {
            ensureSoopDarkMode();
            const root = document.head || document.documentElement;
            if (root && !document.getElementById('__mp_soop_chat_overlay_css__')) {
                const style = document.createElement('style');
                style.id = '__mp_soop_chat_overlay_css__';
                style.textContent = CHAT_CSS;
                root.appendChild(style);
            }

            document.querySelectorAll('video, audio').forEach(el => {
                try {
                    el.muted = true;
                    el.volume = 0;
                } catch (e) {}
            });

            if (document.body) {
                document.body.classList.remove('chat_close', 'close_chat', 'full_screen', 'theater_mode', 'mode_extend');
            }
            const wrap = document.getElementById('webplayer') || document.getElementById('player_wrap');
            if (wrap) {
                wrap.classList.remove('chat_close', 'close_chat', 'mode_extend');
                if (!wrap.classList.contains('chat_open')) {
                    wrap.classList.add('chat_open');
                }
            }

            const chatEl = document.getElementById('chatting_area') || document.querySelector('section.chatting_box');
            if (chatEl) {
                let p = chatEl.parentElement;
                while (p && p !== document.body && p !== document.documentElement) {
                    const cs = window.getComputedStyle(p);
                    if (cs.display === 'none') p.style.setProperty('display', 'block', 'important');
                    if (cs.transform && cs.transform !== 'none') p.style.setProperty('transform', 'none', 'important');
                    if (cs.filter && cs.filter !== 'none') p.style.setProperty('filter', 'none', 'important');
                    if (cs.backdropFilter && cs.backdropFilter !== 'none') p.style.setProperty('backdrop-filter', 'none', 'important');
                    p.style.setProperty('overflow', 'visible', 'important');
                    p.style.setProperty('visibility', 'visible', 'important');
                    p.style.setProperty('opacity', '1', 'important');
                    p = p.parentElement;
                }
            }

            const lp = window.livePlayer && (window.livePlayer._livePlayer || window.livePlayer);
            if (!lp) return;

            if (lp.chatSocket && !lp.chatSocket.__closeProtected) {
                lp.chatSocket.__closeProtected = true;
                const origClose = lp.chatSocket.close.bind(lp.chatSocket);
                lp.chatSocket.close = function() {
                    if (window.__allowSoopChatClose) return origClose();
                };
            }
            if (lp.connectChat && !lp.__chatConnectTriggered && lp.streamConnector && lp.streamConnector.serverSocket) {
                lp.__chatConnectTriggered = true;
                lp.connectChat().catch(function() { lp.__chatConnectTriggered = false; });
            }

            // 로그인 상태인데 숨겨진 백그라운드 플레이어의 프리롤 광고 대기로 채팅 입력/전송이 잠긴 경우 해제
            const isLoggedIn = document.cookie.includes('UserTicket=');
            if (isLoggedIn) {
                const ac = window.liveView && window.liveView.aContainer;
                const cc = ac
                    ? Object.values(ac).find(v => v && typeof v.sendChatMessage === 'function')
                    : null;
                const cw = document.getElementById('chat_write');
                const wa = document.getElementById('write_area');
                const ec = document.getElementById('empty_chat');
                const ecText = ec ? (ec.textContent || '').trim() : '';
                const isAdBlocked = Boolean(
                    (cc && (cc.bBeforeBroadingChatBlock || cc.bPreRollNotice))
                    || (cw && cw.classList.contains('blocked'))
                    || ecText.includes('광고')
                );
                if (isAdBlocked) {
                    try {
                        if (cc && typeof cc.releaseChatBlockBeforeBroading === 'function') {
                            cc.releaseChatBlockBeforeBroading();
                        }
                        if (cc && typeof cc.broading === 'function') {
                            cc.broading();
                        }
                    } catch (e) {}
                    if (cw) cw.classList.remove('blocked');
                    if (wa && wa.getAttribute('contenteditable') !== 'true') {
                        wa.setAttribute('contenteditable', 'true');
                        wa.contentEditable = 'true';
                    }
                    if (ec && ecText.includes('광고')) {
                        ec.textContent = '채팅 입력(c)';
                    }
                }
                const sockOpen = Boolean(
                    lp.chatSocket && lp.chatSocket.socket && lp.chatSocket.socket.readyState === 1
                );
                if (lp.chatSocket && lp.chatSocket.isConnected && lp.chatSocket._isChannelJoined && lp.chatSocket.bWaitJoinComplete) {
                    lp.chatSocket.bWaitJoinComplete = false;
                }
                if (cc && cc.isBroadAndChatEnded && !cc.isBroadEndAndChatClose && sockOpen && !cc.__mpEndedPatched) {
                    try {
                        Object.defineProperty(cc, 'isBroadAndChatEnded', {
                            get: function() { return Boolean(cc.isBroadEndAndChatClose); },
                            configurable: true
                        });
                        cc.__mpEndedPatched = true;
                    } catch (e) {}
                }
            }
        } catch (e) {}
    }

    applySoopChatLayoutAndConnect();
    if (!window.__soopChatTimerStarted) {
        window.__soopChatTimerStarted = true;
        document.addEventListener('DOMContentLoaded', applySoopChatLayoutAndConnect);
        setInterval(applySoopChatLayoutAndConnect, 450);
    }
})();
"""


def is_valid_http_url(url: str) -> bool:
    """http/https 스킴과 유효한 호스트명을 갖춘 URL인지 검사"""
    try:
        parsed = urllib.parse.urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_soop_url(url: str) -> bool:
    """SOOP(구 아프리카TV) 도메인 호스트 여부 검사"""
    try:
        host = urllib.parse.urlparse(url.strip()).hostname or ""
        host = host.lower()
        return any(
            host == d or host.endswith("." + d)
            for d in ("sooplive.com", "sooplive.co.kr", "afreecatv.com")
        )
    except Exception:
        u = url.lower()
        return any(k in u for k in ("sooplive.com", "sooplive.co.kr", "afreecatv.com"))


def fetch_soop_live_bno(bj_id: str) -> str:
    """SOOP 공식 방송국/플레이어 API를 통해 해당 BJ의 현재 진행 중인 실시간 방송번호(BNO)를 조회"""
    safe_bj = urllib.parse.quote(bj_id.strip())
    if not safe_bj or safe_bj.lower() in ("vod", "live", "station", "embed", "directory", "total_search"):
        return ""

    # 1순위: chapi.sooplive.com station API (연령제한/로그인 여부와 무관하게 실시간 broad_no 즉시 반환)
    for chapi_domain in ("chapi.sooplive.com", "chapi.sooplive.co.kr"):
        try:
            req = urllib.request.Request(
                f"https://{chapi_domain}/api/{safe_bj}/station",
                headers={
                    "User-Agent": CHROME_UA,
                    "Referer": "https://www.sooplive.com/",
                }
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                st = json.loads(raw)
                broad = st.get("broad")
                if isinstance(broad, dict):
                    bno = str(broad.get("broad_no", "") or "")
                    if bno and bno.isdigit() and int(bno) > 0:
                        return bno
        except Exception:
            pass

    # 2순위: player_live_api.php 조회
    for domain in ("sooplive.com", "sooplive.co.kr"):
        api_url = f"https://live.{domain}/afreeca/player_live_api.php?bjid={safe_bj}"
        data_payload = urllib.parse.urlencode({
            "bid": bj_id,
            "type": "live",
            "player_type": "html5",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                api_url,
                data=data_payload,
                headers={
                    "User-Agent": CHROME_UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"https://play.{domain}/{safe_bj}",
                    "Origin": f"https://play.{domain}",
                }
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                j = json.loads(raw)
                channel = j.get("CHANNEL", {})
                bno = str(channel.get("BNO", "") or "")
                if bno and bno.isdigit() and int(bno) > 0:
                    return bno
        except Exception:
            pass

    # 3순위: 방송 페이지 HTML 내 nBroadNo 추출
    for domain in ("sooplive.com", "sooplive.co.kr"):
        try:
            req = urllib.request.Request(
                f"https://play.{domain}/{safe_bj}",
                headers={
                    "User-Agent": CHROME_UA,
                    "Referer": f"https://www.{domain}/"
                }
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                final_url = resp.geturl()
                m_final = re.search(r"/([^/?#]+)/(\d{6,})", final_url)
                if m_final:
                    return m_final.group(2)
                html_text = resp.read(65536).decode("utf-8", errors="ignore")
                m_bno = re.search(r"(?:nBroadNo|broad_no|bno)\s*[:=]\s*['\"]?(\d{6,})['\"]?", html_text)
                if m_bno:
                    return m_bno.group(1)
        except Exception:
            pass
    return ""


def normalize_stream_url(url: str) -> str:
    """
    영상 스트림 추출(Streamlink/yt-dlp) 및 채팅 연동을 위해 최신 실시간 BNO가 반영된
    통합 도메인(play.sooplive.com) 본 방송 URL을 반환합니다.
    """
    u = url.strip()
    u_clean = re.sub(r"[?&]vtype=chat", "", u).rstrip("/")

    m_soop = re.search(
        r"https?://(?:(?:play|ch|www|m)\.)?(sooplive\.(?:com|co\.kr)|afreecatv\.com)/(?:station/)?([^/?#]+)(?:/(\d+))?",
        u_clean
    )
    if m_soop:
        bj_id = m_soop.group(2)
        if bj_id.lower() not in ("vod", "live", "directory", "total_search"):
            live_bno = fetch_soop_live_bno(bj_id)
            bno = live_bno if live_bno else m_soop.group(3)
            if bno:
                return f"https://play.sooplive.com/{bj_id}/{bno}"
            return f"https://play.sooplive.com/{bj_id}"

    m_chzzk = re.search(r"https?://chzzk\.naver\.com/(?:live/)?([a-fA-F0-9]{16,})(?:/chat)?", u_clean)
    if m_chzzk:
        return f"https://chzzk.naver.com/live/{m_chzzk.group(1)}"

    return u_clean


def extract_live_chat_url(url: str, already_normalized: bool = False) -> str:
    """
    플랫폼별 전용 채팅 URL 반환:
    - SOOP: LivePlayer 채팅 소켓과 #chatting_area가 정상 구동되는 본 방송 URL 반환
    - CHZZK / Twitch / YouTube: 각 플랫폼 전용 팝아웃 채팅 URL 반환
    """
    u = url.strip()

    m_chzzk = re.search(r"chzzk\.naver\.com/(?:live/)?([a-fA-F0-9]{16,})", u)
    if m_chzzk:
        cid = m_chzzk.group(1)
        return f"https://chzzk.naver.com/live/{cid}/chat"

    if is_soop_url(u):
        norm = u if already_normalized else normalize_stream_url(u)
        parsed = urllib.parse.urlparse(norm)
        host = (parsed.hostname or "").lower()
        if host.startswith("vod.") or re.search(r"/(?:vod|directory|total_search)(?:/|$)", parsed.path.lower()):
            return ""
        return re.sub(r"[?&]vtype=chat", "", norm).rstrip("/")

    m_twitch = re.search(r"twitch\.tv/([a-zA-Z0-9_]+)", u)
    if m_twitch:
        channel = m_twitch.group(1)
        return f"https://www.twitch.tv/popout/{channel}/chat?popout="

    m_yt = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/live/)([a-zA-Z0-9_-]{11})", u)
    if m_yt:
        vid = m_yt.group(1)
        return f"https://www.youtube.com/live_chat?v={vid}"

    return ""


class StreamlinkResolverThread(QThread):
    chat_ready = pyqtSignal(str, str)
    resolved = pyqtSignal(str, str, str, bool, str, str, object)
    failed = pyqtSignal(str, str)

    def __init__(
        self,
        target_url: str,
        cookies_snapshot: list = None,
        preferred_quality: str = "best",
        parent=None
    ):
        super().__init__(parent)
        self.target_url = target_url
        self.cookies_snapshot = cookies_snapshot or []
        self.preferred_quality = preferred_quality or "best"

    def _apply_cookies_to_streamlink(self, session):
        for dom, name, val in self.cookies_snapshot:
            if not name or val is None:
                continue
            try:
                session.http.cookies.set(name, val, domain=dom)
                if "sooplive" in dom or "afreecatv" in dom:
                    session.http.cookies.set(name, val, domain=".sooplive.com")
                    session.http.cookies.set(name, val, domain=".sooplive.co.kr")
            except Exception:
                pass

    def _pick_streamlink_quality(self, streams: dict) -> tuple:
        quality_urls = {}
        for q_name, s_obj in streams.items():
            try:
                u = s_obj.to_url()
                if u:
                    quality_urls[q_name] = u
            except Exception:
                pass

        if not quality_urls:
            return None, {}

        pref = self.preferred_quality
        priority = []
        if pref and pref != "best":
            priority.append(pref)
        priority.extend(["best", "1080p60", "1080p", "720p60", "720p", "480p", "360p"])

        chosen_q = None
        for q in priority:
            if q in quality_urls:
                chosen_q = q
                break
        if not chosen_q:
            chosen_q = list(quality_urls.keys())[-1]

        return chosen_q, quality_urls

    def run(self):
        patch_urllib3_percent_re()
        normalized_url = normalize_stream_url(self.target_url)
        chat_url = extract_live_chat_url(normalized_url, already_normalized=True)
        if chat_url:
            self.chat_ready.emit(normalized_url, chat_url)

        if HAS_STREAMLINK:
            candidate_urls = [normalized_url]
            if "sooplive.com" in normalized_url:
                candidate_urls.append(normalized_url.replace("sooplive.com", "sooplive.co.kr"))
            elif "sooplive.co.kr" in normalized_url:
                candidate_urls.append(normalized_url.replace("sooplive.co.kr", "sooplive.com"))

            for try_url in candidate_urls:
                try:
                    session = streamlink.Streamlink()
                    session.set_option("http-headers", {
                        "User-Agent": CHROME_UA,
                        "Referer": "https://play.sooplive.com/"
                    })
                    self._apply_cookies_to_streamlink(session)
                    streams = session.streams(try_url)
                    if streams:
                        chosen_q, quality_urls = self._pick_streamlink_quality(streams)
                        if chosen_q and quality_urls:
                            stream_url = quality_urls[chosen_q]
                            is_live = not ("youtube.com/watch" in self.target_url or "youtu.be/" in self.target_url)
                            self.resolved.emit(
                                normalized_url, stream_url, chosen_q, is_live,
                                normalized_url, chat_url, quality_urls
                            )
                            return
                except Exception as e:
                    print(f"[Streamlink 시도 ({try_url})] {e}")

        if HAS_YTDLP:
            candidate_urls = [normalized_url]
            if self.target_url != normalized_url:
                candidate_urls.append(self.target_url)
            for try_url in candidate_urls:
                try:
                    ydl_opts = {
                        'format': 'best[acodec!=none][vcodec!=none]/best[ext=mp4]/best',
                        'quiet': True,
                        'no_warnings': True,
                        'noplaylist': True,
                        'http_headers': {'User-Agent': CHROME_UA}
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(try_url, download=False)
                        stream_url = info.get('url', '')
                        is_live = bool(info.get('is_live', False)) or bool(chat_url)
                        title = info.get('title', normalized_url)
                        vid_id = info.get('id', '')
                        if is_live and vid_id and ("youtube.com" in self.target_url or "youtu.be" in self.target_url):
                            chat_url = f"https://www.youtube.com/live_chat?v={vid_id}"

                        quality_urls = {}
                        for fmt in info.get('formats', []) or []:
                            f_url = fmt.get('url', '')
                            if not f_url:
                                continue
                            if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                                height = fmt.get('height')
                                fps = fmt.get('fps')
                                label = f"{height}p{int(fps)}" if height and fps and fps > 30 else (
                                    f"{height}p" if height else fmt.get('format_note', fmt.get('format_id', ''))
                                )
                                if label:
                                    quality_urls[label] = f_url
                        if stream_url and "best" not in quality_urls:
                            quality_urls["best"] = stream_url

                        chosen_q = "yt-dlp"
                        if self.preferred_quality in quality_urls:
                            stream_url = quality_urls[self.preferred_quality]
                            chosen_q = self.preferred_quality

                        if stream_url:
                            self.resolved.emit(
                                normalized_url, stream_url, chosen_q, is_live, title, chat_url, quality_urls
                            )
                            return
                except Exception as e:
                    print(f"[yt-dlp 시도 ({try_url})] {e}")

        err_msg = "streamlink/yt-dlp 미설치" if (not HAS_STREAMLINK and not HAS_YTDLP) else "스트림 추출 불가(방송 종료/연령제한 등)"
        self.failed.emit(normalized_url, err_msg)
