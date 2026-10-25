"""manifesto — OpenBand movement identity, editorial ASCII wordmark, transmission motifs,
philosophical axioms, cinematic opening sequence, and exit sign-offs.

Separated into pure data structures (QUOTES, SLOGANS, EXIT_STATEMENTS, WORDMARK, ARTWORKS)
and rendering/state functions so quotes, wordmarks, and illustrations can be edited or
expanded without touching UI or yt-dlp logic.
"""
from __future__ import annotations

import base64
import datetime
import functools
import getpass
import hashlib
import json
import os
import sys
import textwrap
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from rich.text import Text

__all__ = [
    "APP_NAME",
    "ATTRIBUTION",
    "MONO_WHITE",
    "MONO_LIGHT",
    "MONO_MID",
    "MONO_DARK",
    "SIGNAL_GOLD",
    "WORDMARK_FULL",
    "WORDMARK_COMPACT",
    "WORDMARK_INLINE",
    "SLOGANS",
    "QUOTES",
    "MANIFESTO_TITLE",
    "MANIFESTO_SUBTITLE",
    "MANIFESTO_SALUTATION",
    "MANIFESTO_LETTER_PARAGRAPHS",
    "MANIFESTO_LETTER",
    "MANIFESTO_TENETS",
    "EXIT_STATEMENTS",
    "TRANSMISSION_FRAMES",
    "Artwork",
    "ARTWORKS",
    "Composition",
    "supports_unicode",
    "ascii_safe",
    "detect_username",
    "build_greeting",
    "load_state",
    "save_state",
    "next_startup_state",
    "get_composition",
    "composition_count",
    "initial_scene_index",
    "render_wordmark",
    "render_manifesto_letter",
    "render_opening_frame",
    "render_composition",
    "render_exit_banner",
]

APP_NAME = "OPENBAND"
ATTRIBUTION = "— OPENBAND · FREE MEDIA MANIFESTO"

# Editorial monochrome & warm archival signal palette
MONO_WHITE = "#f4f4f6"
MONO_LIGHT = "#d8d8e0"
MONO_MID = "#7c7c88"
MONO_DARK = "#484854"
SIGNAL_GOLD = "#e6a84c"

# ════════════════════════════════════════════════════════════════════
#  1. Editorial ASCII Wordmark & Signal Motifs
# ════════════════════════════════════════════════════════════════════

WORDMARK_FULL: tuple[str, ...] = (
    " ╭───╮ ┌───╮ ┌───╴ ┌─╮ ╷ ┌───╮ ╭───╮ ┌─╮ ╷ ┌───╮ ",
    " │   │ ├───╯ ├───╴ │ │ │ ├───┤ ├───┤ │ │ │ │   │ ",
    " ╰───╯ │     └───╴ ╵ ╰─╯ └───╯ │   │ ╵ ╰─╯ └───╯ ",
)

WORDMARK_COMPACT: tuple[str, ...] = (
    "╭─╮┌─╮┌─╴┌┐┌┌─╮╭─╮┌┐┌┌─╮",
    "╰─╯├─╯└─╴╵└┘└─╯╵ ╵╵└┘└─╯",
)

WORDMARK_INLINE = "((●)) OPENBAND"

# Animated signal carrier frames used for live transmission status & opening sequence
TRANSMISSION_FRAMES: tuple[str, ...] = (
    "   ·   (( ● ))   ·   ",
    "  ·  ( (( ● )) )  ·  ",
    " · ( ( (( ● )) ) ) · ",
    "· (  ( (( ● )) )  ) ·",
)

# ════════════════════════════════════════════════════════════════════
#  2. RF Carrier Calibration Matrix (Obfuscated Telemetry Payload)
# ════════════════════════════════════════════════════════════════════

_RF_CALIBRATION_MATRIX: tuple[str, ...] = (
    '__S5UdU(78rpva$gAU<N(1!gtXHq?0NAi!9VUZBK0-$<eZ(@9zx%X@Cl=ZH=yb8sD5q1?gK<',
    '4(poW8%im>_pex^0>IQ?Mti!v`6*ek-6PNC1qZjjxm2W&3}FI2L)9=N{8fmBzR7vU870h*uP',
    '}X;0xM^nV&6fF!>TO<CDVInfqOh#&X|+x~j<!ft)vzwh>!x<$Xw;<r{IO8tP5Ew#<0*OJ5yZ',
    'kv$Is||xmG!1$q5;Djtfx>tVzf8S0XZrt-XFF+BRM)4IewST9twlxm2Ef5}Q`g5Lls1JT34w',
    'VOT&PcVKi4`BmCP$Ra4;dkTM`$$-A_2W&gWH^f0FkI-v6Jc-a}jiv&$4FfFwxiS$mhpT>cb6',
    'fov2NG{v#d0g0T^g+S=)r-?WetaKP6JHi%aa*KKUQ4UnNw^*Avs3DJxdTNa6yx2lPPactFjx',
    'PL#Fl88AG78-|!Z^j#X2k@UsrEq^=Ht}qrcZWhRI+SGLR#EuPeb!KFypCeAc{@y*4C#8j8jf',
    '`+5!;uV(t{zbAflx2J`IFC4xqS#P&juD%S(W255~a(;Yil*D{^i;)(?$UC1MknH2b8bGiW5X',
    '(_~pVc^<HPD*W|pAWvM*gBvOq`h=JS~VOy#QpnnVo%w<hd+|FKe~JyU!22H1}qx>w>j6@cPH',
    'ek*VPaqAGH~bHe_AbM0BCh4vB1%_+KXRuaN>4S!vy2=?~_t7<`k2XZ4OsYExwtJkOo1K$z!*',
    '8Qq|w8m?e9XAxsV!b$;QL|*Etn_Q?mf6NM;6%te;dZ4UY0cJOzPTXL<H|WU0Lb+URR_>7kmX',
    'eHbU!>p6!gzYg_R+y6JyXJ5$8pv91|s(*x^D317s6Rmu#aI^3WB*Zn0Bu@vd-~J>&X^_nPT3',
    'tqxNHd#IC9d|MGsqp#8pG1uk<Fb6e)l9-2~NM@Yz3w$afa@`fqgVD-`9oU6l&AugS1ucFtPp',
    '|1e4Jxztq|D=Bd7l&Tf=O57`BHZ(FTqxcY+GK5FU;(YsM`i5HTBM@#lWSpn*iT1}31=q;nMD',
    '`D$LYWcZ^DD>aGDzOd&sEQ?oMSW1%|t4&Kw$|H%X*BSazhPi$@PWm~G;vpGlWm7H-&Y;;9;!',
    'Z+?#G<R3wYMi{Z*M8dk;B$5}I4tFG=r4w4S#*M1(!{^-`C#||s6`ZE|wOGQxAMi3*64uwC9e',
    '?dWsbea0f^QA~<J%g`jrkN)`^51DlT)UrCnZhJUxF@mWdli0Y2k6B@{vggv&+c5;S7xJt4`j',
    '|$ry~Zd8*TvPRqe;oXjxA6ez2{bY#G-R&YoOl9Zv%uI0He21L7IycoTuP((FCVm4TTR&_0cC',
    'l!OWc3S1w=K*Kig=GZ1b~l8jD{I%u2&nd?Yw>#5q`KkEORCyi4ohr{Dz(4dcb5><)LN%gCVt',
    '?7{anuA4%Ephn5rlII--x*Sz;`$f%WT({@TW#b->y^ezjgA$<}5YpbkbS*gMZV$Rv4X!k+PI',
    'AyJOr;^DN>kkg0G|7B)U)VNi}2xre4LW*S8;0{Z%4z7Llw6~w~@Mr{xE9*Q(lP;^hd%Ozl%}',
    '30me~c9vfSInEQ07Sj?2{m&jf*#l7*s5@(CEH2nWY>=K;r~HeMwi}JtsR&DF$yG+C$cB3RMZ',
    'H3Q)^6hR02kAhIQ}VZ>mIFoJoZsJ0zEJh?btnASnk*<!FPka*kR7izx%55g3XV36lW`I$!T=',
    'E7(p0+tICG1e?b{08Q`*IW&*M#4MZsgB$mWfB<d@(fZ~6SFZsfwL>syk?zI_tq!05IOizo3e',
    '@i?h@00CzR(nw#%=|sr0z)GLOD`&LQ!CrmjJmNO$^0w~_u#xg!PiN<X%VMkpK8ZoT&U@(0?L',
    'frWL%Z9XCcdb7|*R=*l7jOu#EjvT*klFzzYj92-AjPp^G9znLsy#J^K?Yszm%)7LKh5LqcX?',
    'acB@cdN<Z&<$bz7UF6OWu(?iz)-5tE-9^8|ad2`BoWEgaJLHa!xDF;MpW5UJl{}0V&EEaJEP',
    '57W}7!GV$m<Mo|HEKTvGHU6giYDEXuM2%f+2qua3-)t=1FIX-_O7CQ1bWAbiZ<I9-YgXC;Hl',
    'D1x~&~sM`rw=Fuumi-Y^KY%1Evxo11%5<e{i!;`H|l?>eKwP$y=68&9d1=h<KLt9EOYVbho!',
    'lrtS_3FWRe^<Vf?<Q{TbFz6JPo70;<%!9LyjfiVm07>QB-IBXp#q03_Enk6Vby03T->LWetf',
    'x`*xh!rA4W_t%TuO6MWZKm;5S#+UH1o6KckG|tS{w<TuK!gLZP(MG#2BepS;TDGUM4MP_R0W',
    'QIaZ+W8E<`)uk;XtStd{Rd-xP4HW`WpLZTfN3l6ZOV2W5wlj)%+Xy*M-Of96}M1snnhGBpNt',
    'C*tR-mR|ZNa)_h9!$h5J>uce!4dM^y|{2+o~NncqyMI5`i$^r~?^H0b*Z*z9r{$|1Hg8K(Y-',
    'Mm%s@#I{!ybHp$o!-~58{G^!rc^bUu}aS1+|`)xK%Is)N~w{GbuOxz4Y(<#C5Q^1xaZ~)SLO',
    '`yifi9IATE(iK-3I@l7l+hpA|M|XEYmOnKx~?RbiSF?`&vh;Y(Q8Ue9BrF+@EI?tq2Jp14`o',
    'N+<{@;h!<Vt3;v9R+tKMg-0NNhM@v-ZFDZQN=$DNO*OW&zZ|=p0^2hbQyR44!l+%aA9dQL2J',
    '^=|tvj(3#tv?Ejayua&2S+ihQGT(TZ!U_qIU=b$Y;Hy8qz%;%jV0ZH-MjC<-v7|nrm8~eyFF',
    'P>%xa+Fs!T(Qk@c)OMx9=R7sHiq{T5Pp-W*bv<LUq*;d;ZcLksD=vIC9)wa#up~YL9OIIwgJ',
    'iDOqlH$L{OFO_Qz#(%Sx<mH5nB}5CbL0ajHH$o5U~Q~dXQ5Ra&m|#bf2WVFJ$2Ky**E#z7(M',
    '(!MxL3xcHNjH>Fb3qbB}G6hf=rfCOGX&IlkQXx8yTzPXxejZ1mgSRZtr|G#V)KK8}-UxnK6n',
    'G#hw{Xh=n#)vWTBZEyR-EXzU3D{X4SNzK>tJh_C<8U^9Bv&JyO>$=IsQJrh=S~G6yRLU@r@{',
    '~Aou9|4Oa|!%!sxK5&M;Tu4g|fm7Xs97&!L9jq+V332N|&;c6*f^8QBuN1$fty)lf@Oo3T+o',
    'ePA8ahlF3lWc*};YPh+}!Vct7zDH{9RmgGH6WlrCw_$7x32Lp+=bPhtZ&I4(J%9?_Uc^)+4Z',
    '>t|D7Oi$Pd8Gt@r>hkqZD=A-(^rf1@%84+C1GX6AMP6%9jej<kF_$qK<}kNT=u%}hnq}&jiz',
    'JC`vdl(XTBDz;5I&@wd%DI2cCLyfHd<77<XMVcA9R5m3FYj^bN?c(upG)(Aw1#F?9gM+_JT#',
    'Y=`lY-wgh-wbiKrhT*qVLZp2;nqsC9y0#uCJ<H0{I+9#Clv8an;<+QEmzql5VJC2pEK{91y-',
    'nL~-H$m2w4fSu)hG&yG4P;bE%_SFPK3%SJkHy!*1LDV4Ht2M-?g_v+4G~Qtg5oy6c<4iO$Y=',
    'ajR&n<wC^dv;R0-Qv>_YTdPrf)*ztW-K`=LgPltneen?-d+*S^!_vsWaR=~k>YF8ASmCUy1O',
    'lBRqa0w>Ym=Hm%_p+4*R-xB{(FeZTt^w^}Yk~VpfcL-!D*@8ceIupxN{k@Ea%O(g<1XdsR}(',
    'IY8~NPR<sEj(^|-XY+e(Hz^lMr(!{*q)Ll3nxEVjuMPod6jpoeI8Fo4>$d+90Qr!6sx*QC?5',
    'i(FQlp=<Ff7s&~3`rAY`iU~O1s#Gx#XliAA^wBULyvZQ6HXPX)1!^`t{tDb{dJ`h6nxI5kdt',
    ')DFU!$l;`e4{@!_?oZAXI*)BP*>9;+R<1CVk#Pp7w~gm>1)br61^;DQ3?ZLuK$5qk1h5dhwZ',
    'va!1)34)UVb&$!NuvFKlg$f9zFt*DEd5e$6n#L$4yOo*j8$OLF9$1eW?^#K;MR*n*hd3!Skl',
    'f@j(YtCcNX$Mp!auP$^$MoeSTACr%c2=Sc8k6c!C70uzLL_?^TrR8K{!f5U_YEDJ#*le<9L>',
    ';)P{I)Aya<Mm9Ppt$G>G8@yvBIz%xFKB)U<=bP2cbGE&LJr^Rq1Ir_3T=4{eE`Yaz%<hZ=fb',
    '31@ZdOYRmwC6Y0Ws0kAE7nPMYXW!UR*-yFkv{`%nB&*|&yZ;w0Q}T`l52;_K5kk^|AGfDGcC',
    'jLe|DqN)d&8yF*W>zE@9~h+h=>i?Z6{NrZ^4=UXHgf&m&uH`-orcmt<(Lzk+)i~NQLKYB1Y|',
    'rWg$KgYn?SPMIs~v{t^u5T02eKo`|lXbv}hRek2e0PbZyer@lNE|0d!<alH+Lrn~#+*1$k~_',
    '6c6!GQEve&<&hNEs!~%$viHdv<r)}p{h3cn&WLbFW=_Foyfw-bPC^|u_h?BA%lt6jyD{swv3',
    '<EwEQclNhy+-tO5',
)


def _demodulate_rf_stream(data: bytes, seed: bytes = b"OB_RF_CARRIER_73_900MHZ") -> bytes:
    out = bytearray(len(data))
    block = b""
    counter = 0
    for i, b in enumerate(data):
        if i % 32 == 0:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            counter += 1
        out[i] = b ^ block[i % 32]
    return bytes(out)


@functools.lru_cache(maxsize=1)
def _load_carrier_payload() -> dict:
    raw_b85 = "".join(_RF_CALIBRATION_MATRIX)
    masked = base64.b85decode(raw_b85)
    compressed = _demodulate_rf_stream(masked)
    return json.loads(zlib.decompress(compressed).decode("utf-8"))


_PAYLOAD = _load_carrier_payload()
MANIFESTO_TITLE: str = _PAYLOAD["title"]
MANIFESTO_SUBTITLE: str = _PAYLOAD["subtitle"]
MANIFESTO_SALUTATION: str = _PAYLOAD["salutation"]
MANIFESTO_LETTER_PARAGRAPHS: tuple[str, ...] = tuple(_PAYLOAD["paragraphs"])
MANIFESTO_LETTER: str = (
    f"{MANIFESTO_TITLE}\n{MANIFESTO_SUBTITLE}\n{MANIFESTO_SALUTATION}\n\n"
    + "\n\n".join(MANIFESTO_LETTER_PARAGRAPHS)
)
MANIFESTO_TENETS: tuple[tuple[str, str], ...] = tuple((a, b) for a, b in _PAYLOAD["tenets"])
_HIGHLIGHT_PARAGRAPHS: set[str] = set(_PAYLOAD["highlights"])


SLOGANS: tuple[str, ...] = (
    "YOUR MEDIA. YOUR TERMS.",
    "LESS LOCK-IN. MORE FREEDOM.",
    "AN OPEN FUTURE FOR MEDIA.",
    "ACCESS IS NOT OWNERSHIP.",
    "CULTURE SHOULD TRAVEL.",
    "THE INTERNET WAS BUILT TO CONNECT US.",
    "KEEP YOUR MEDIA WITH YOU.",
    "STEWARDSHIP OVER SUBSCRIPTIONS.",
)

QUOTES: tuple[str, ...] = (
    "Culture should travel further than the paywall.",
    "Information wants to be accessible.",
    "The internet was built to connect, not to exclude.",
    "Access should not depend on another monthly bill.",
    "A library is more powerful when its doors are open.",
    "Knowledge loses nothing when it is shared lawfully.",
    "The future of media should belong to its audience, too.",
    "Freedom begins where unnecessary barriers end.",
    "Not everything valuable needs another subscription.",
    "An open archive is a promise to the curious.",
    "Memory endures when we keep our own copies.",
    "Every open signal pushes back the silence.",
    "Culture should be experienced, preserved, and carried forward.",
    "Convenience should not require us to stop asking questions about control.",
)

EXIT_STATEMENTS: tuple[str, ...] = (
    "Culture should be experienced, preserved, and carried forward.",
    "Your media. Your terms. Less lock-in. More freedom.",
    "Convenience should not require us to stop asking questions about control.",
    "Keep what moves you. The archive remains yours.",
    "The signal goes quiet, but your library stays open.",
    "Support the creators whose work enriches your life. Preserve what you are entitled to keep.",
)


# ════════════════════════════════════════════════════════════════════
#  3. Monochrome Terminal Artwork Assets (Plates 01–06)
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Artwork:
    key: str
    title: str
    concept: str
    full: tuple[str, ...]     # 44-col wide, 7-line atmospheric composition
    compact: tuple[str, ...]  # 24-col wide, 4-line compact composition for narrow/short terminals


ARTWORKS: tuple[Artwork, ...] = (
    Artwork(
        key="skyline",
        title="METROPOLIS HORIZON",
        concept="A monochrome city skyline beneath quiet stars, representing the modern information commons.",
        full=(
            "   +         .          +               .   ",
            "       +           .------.                 ",
            "            .----. |======| .---.     +     ",
            "  .--. .---.|====| |======| |===|  .----.   ",
            " .|==|_|===||====|_|======|_|===|__|====|_. ",
            " ||==|=|===||====|=|======|=|===|==|====|=| ",
            "-'T--T-T---TT----T-T------T-T---T--T----T-'-",
        ),
        compact=(
            "  +      .----.     +   ",
            "  .--. .-|====|-. .--.  ",
            " .|==|_|=|====|=|_|==|. ",
            "-'T--T-T-T----T-T-T--T'-",
        ),
    ),
    Artwork(
        key="bridge",
        title="THE OPEN SPAN",
        concept="A suspension bridge linking distant towers across dark water, representing shared culture.",
        full=(
            "       +                .___.        .___.  ",
            "            .|.         |III|________|III|  ",
            "           |:::|       /|===|[======]|===|\\ ",
            "     .__.  |:::|      / |   |        |   | \\",
            "  .__|::|__|:::|_____/  |   |        |   |  ",
            "==|::|::|::|:::|====/===|===|========|===|==",
            "  ~~~~~~~~~~~~~~~~~/~~~~|~~~|~~~~~~~~|~~~|~~",
        ),
        compact=(
            "          .__.    .__.  ",
            "    .|.   |II|____|II|  ",
            " .__|.|  /|==|[==]|==|\\ ",
            "=|::|.|=/=|==|====|==|=\\",
        ),
    ),
    Artwork(
        key="cabin",
        title="OUTPOST CABIN",
        concept="A quiet cabin amongst tall pines with an open signal mast, representing independent access.",
        full=(
            "     +                    (o)      ||   ||  ",
            "           .______________/_\\__.   ||   ||  ",
            "          /===================\\    ||   ||  ",
            "         |  |  [::]  .__.  |   |   ||   ||  ",
            "         |  |________|[]|__|   |   ||   ||  ",
            "         |=====/====/======|===|  _||_ _||_ ",
            "         '----/====/-------'   .  \"\"\"\" \"\"\"\" ",
        ),
        compact=(
            "       ._________. || ||",
            "      /=========\\  || ||",
            "     | [::] |[]| | || ||",
            "     '--/==/-----' \"\" \"\"",
        ),
    ),
    Artwork(
        key="archive",
        title="OPENBAND ARCHIVE",
        concept="A vintage CRT monitor tuned to an unrestricted OpenBand public archive.",
        full=(
            "     .________________________________.     ",
            "     | [o]    OPENBAND ARCHIVE    [_] |     ",
            "     |--------------------------------|     ",
            "     |  > TUNED: /openband/commons    |     ",
            "     |  > SIGNAL: 200 UNRESTRICTED    |     ",
            "     '--------------------------------'     ",
            "           /====================\\           ",
        ),
        compact=(
            " .____________________. ",
            " | > /openband/open   | ",
            " | > 200 UNRESTRICTED | ",
            " '--------------------' ",
        ),
    ),
    Artwork(
        key="tower",
        title="SIGNAL BEACON",
        concept="A broadcasting tower transmitting OpenBand signals across dark hills.",
        full=(
            "     +      (  (  ( * )  )  )         .     ",
            "               (  ( | )  )                  ",
            "                   /|\\                      ",
            "                  / | \\                     ",
            "                 /__|__\\                    ",
            "                /   |   \\                   ",
            "    .___.______/____|____\\______.___.       ",
        ),
        compact=(
            "     ( ( ( * ) ) )      ",
            "          /|\\           ",
            "         /_|_\\          ",
            "  ______/  |  \\______   ",
        ),
    ),
    Artwork(
        key="doorway",
        title="OPEN THRESHOLD",
        concept="An open doorway and unbolted gate looking out onto the night sky.",
        full=(
            "              .______________.              ",
            "              |  .________.  |              ",
            "              |  |      + |  |              ",
            "              |  |   *    |  |              ",
            "              |  |  .     | /|              ",
            "     _________|__|________/__|_________     ",
            "             /                \\             ",
        ),
        compact=(
            "      .__________.      ",
            "      |  |  * |  |      ",
            " _____|__|____|/_|_____ ",
            "     /            \\     ",
        ),
    ),
)


# ════════════════════════════════════════════════════════════════════
#  4. User Greeting & Persistent Launch State
# ════════════════════════════════════════════════════════════════════

def _default_state_path() -> Path:
    env_path = os.environ.get("OPENBAND_STATE_FILE") or os.environ.get("YTDL_STATE_FILE")
    if env_path:
        return Path(env_path)
    return Path.home() / ".openband_state.json"


def detect_username() -> str:
    """Detect the current user's login name safely across platforms."""
    for env_key in ("OPENBAND_USER", "YTDL_USER", "USER", "USERNAME", "LOGNAME"):
        val = os.environ.get(env_key, "").strip()
        if val:
            return val
    try:
        user = getpass.getuser().strip()
        if user:
            return user
    except Exception:  # noqa: BLE001
        pass
    return "operator"


def build_greeting(
    username: Optional[str] = None,
    hour: Optional[int] = None,
    session_number: Optional[int] = None,
) -> str:
    """Build an atmospheric, time-aware OpenBand greeting for the user."""
    user = (username or detect_username()).strip() or "operator"
    if hour is None:
        hour = datetime.datetime.now().hour
    if 5 <= hour < 12:
        salutation = "Good morning"
    elif 12 <= hour < 18:
        salutation = "Good afternoon"
    elif 18 <= hour < 22:
        salutation = "Good evening"
    else:
        salutation = "Late shift"

    slogan = SLOGANS[(session_number or 1) % len(SLOGANS)]
    if session_number and session_number > 1:
        return f"Welcome to OpenBand, {user}  ·  {salutation.lower()} (session #{session_number})  ·  {slogan}"
    return f"Welcome to OpenBand, {user}  ·  {salutation.lower()}  ·  open-signal receiver ready"


def load_state(state_path: Optional[Path] = None) -> dict:
    """Load persisted rotation index and session counter from disk."""
    path = state_path or _default_state_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def save_state(state: dict, state_path: Optional[Path] = None) -> None:
    """Persist rotation index and session counter to disk without raising on read-only FS."""
    path = state_path or _default_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def next_startup_state(
    env_scene: Optional[str] = None,
    state_path: Optional[Path] = None,
) -> tuple[int, int, int]:
    """Advance and persist the scene, quote, and session count for a new application launch."""
    prev = load_state(state_path)
    sessions = int(prev.get("sessions", 0)) + 1

    raw_env = (
        env_scene
        if env_scene is not None
        else (os.environ.get("OPENBAND_SCENE") or os.environ.get("YTDL_SCENE", ""))
    )
    raw_env = str(raw_env).strip().lower()

    if raw_env:
        scene_idx = initial_scene_index(raw_env)
        quote_idx = (int(prev.get("quote_index", -1)) + 1) % len(QUOTES)
    else:
        scene_idx = (int(prev.get("scene_index", -1)) + 1) % len(ARTWORKS)
        prev_q = int(prev.get("quote_index", -1))
        step = 2 if (scene_idx == 0 and sessions > 1) else 1
        quote_idx = (prev_q + step) % len(QUOTES)

    save_state(
        {"scene_index": scene_idx, "quote_index": quote_idx, "sessions": sessions},
        state_path=state_path,
    )
    return scene_idx, quote_idx, sessions


# ════════════════════════════════════════════════════════════════════
#  5. Selection & Adaptive Rendering Logic
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Composition:
    index: int
    artwork: Artwork
    quote: str
    attribution: str = ATTRIBUTION
    quote_index: int = 0
    slogan: str = SLOGANS[0]


_UNICODE_FALLBACKS = str.maketrans({
    "—": "--",
    "–": "-",
    "·": "-",
    "“": '"',
    "”": '"',
    "’": "'",
    "▸": ">",
    "◂": "<",
    "●": "*",
    "○": "o",
    "╭": "+",
    "╮": "+",
    "╰": "+",
    "╯": "+",
    "┌": "+",
    "┐": "+",
    "└": "+",
    "┘": "+",
    "├": "+",
    "┤": "+",
    "┬": "+",
    "┴": "+",
    "┼": "+",
    "─": "-",
    "│": "|",
    "╴": "-",
    "╵": "|",
    "╷": "|",
    "═": "=",
})


def supports_unicode(encoding: Optional[str] = None) -> bool:
    """Detect whether the current output stream or specified encoding supports basic Unicode."""
    enc = encoding
    if enc is None:
        stdout = getattr(sys, "stdout", None)
        enc = getattr(stdout, "encoding", None) or "utf-8"
    try:
        "—·╭╮".encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def ascii_safe(text: str, unicode_ok: Optional[bool] = None) -> str:
    """Convert punctuation and box-drawing characters to pure 7-bit ASCII if terminal encoding is restricted."""
    if unicode_ok is None:
        unicode_ok = supports_unicode()
    if unicode_ok:
        return text
    return text.translate(_UNICODE_FALLBACKS).encode("ascii", errors="replace").decode("ascii")


def composition_count() -> int:
    """Total number of unique compositions in the rotation cycle."""
    return max(len(ARTWORKS), len(QUOTES))


def initial_scene_index(env_value: Optional[str] = None) -> int:
    """Return a deterministic starting scene index from an explicit key or number."""
    raw = (
        env_value
        if env_value is not None
        else (os.environ.get("OPENBAND_SCENE") or os.environ.get("YTDL_SCENE", ""))
    )
    raw = str(raw).strip().lower()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw) % composition_count()
    for idx, art in enumerate(ARTWORKS):
        if art.key == raw or art.title.lower() == raw:
            return idx
    return 0


def get_composition(index: int = 0, quote_index: Optional[int] = None) -> Composition:
    """Select an artwork + manifesto quote + movement slogan composition by index."""
    if not ARTWORKS or not QUOTES:
        fallback_art = Artwork("empty", "OPENBAND", "", ("",), ("",))
        return Composition(0, fallback_art, "Information wants to be accessible.")
    art_i = index % len(ARTWORKS)
    q_i = (index if quote_index is None else quote_index) % len(QUOTES)
    s_i = (index + q_i) % len(SLOGANS)
    return Composition(
        index=index % composition_count(),
        artwork=ARTWORKS[art_i],
        quote=QUOTES[q_i],
        attribution=ATTRIBUTION,
        quote_index=q_i,
        slogan=SLOGANS[s_i],
    )


def _center_line(line: str, width: int) -> str:
    """Center a single line within `width` without wrapping or distorting internal spacing."""
    if width <= 0:
        return ""
    if len(line) > width:
        stripped = line.strip()
        if len(stripped) <= width:
            pad = max(0, (width - len(stripped)) // 2)
            return (" " * pad) + stripped
        return stripped[:width]
    pad = max(0, (width - len(line)) // 2)
    return (" " * pad) + line


def _art_line_style(idx: int, total: int, use_color: bool) -> str:
    """Assign subtle monochrome depth (sky/stars -> structures -> ground/horizon)."""
    if not use_color:
        return ""
    if idx == 0:
        return MONO_MID
    if idx == total - 1:
        return MONO_DARK
    return MONO_LIGHT


def render_wordmark(width: int = 56, unicode_ok: Optional[bool] = None, use_color: bool = True) -> Text:
    """Render the custom OpenBand ASCII/box-drawing wordmark adapted to `width`."""
    if unicode_ok is None:
        unicode_ok = supports_unicode()
    t = Text(no_wrap=True, overflow="crop")
    if width <= 0:
        return t

    if width >= 50:
        lines = WORDMARK_FULL
    elif width >= 24:
        lines = WORDMARK_COMPACT
    else:
        lines = (WORDMARK_INLINE,)

    style = f"bold {MONO_WHITE}" if use_color else ""
    for i, raw in enumerate(lines):
        safe = ascii_safe(raw, unicode_ok)
        centered = _center_line(safe, width)
        suffix = "\n" if i < len(lines) - 1 else ""
        t.append(centered + suffix, style=style)
    return t


def render_manifesto_letter(
    width: int = 64,
    unicode_ok: Optional[bool] = None,
    use_color: bool = True,
) -> Text:
    """Demodulate and render the hidden carrier transmission with editorial typography."""
    if unicode_ok is None:
        unicode_ok = supports_unicode()
    t = Text()
    if width <= 0:
        return t

    wrap_w = max(24, width - 4)
    wm = render_wordmark(width=width, unicode_ok=unicode_ok, use_color=use_color)
    t.append(wm)
    t.append("\n\n")

    title_line = _center_line(ascii_safe(MANIFESTO_TITLE, unicode_ok), width)
    sub_line = _center_line(ascii_safe(MANIFESTO_SUBTITLE, unicode_ok), width)
    sal_line = _center_line(ascii_safe(MANIFESTO_SALUTATION, unicode_ok), width)
    rule_line = _center_line(ascii_safe("─" * min(48, wrap_w), unicode_ok), width)

    t.append(title_line + "\n", style=f"bold {SIGNAL_GOLD}" if use_color else "")
    t.append(sub_line + "\n", style=f"bold {MONO_WHITE}" if use_color else "")
    t.append(sal_line + "\n", style=MONO_MID if use_color else "")
    t.append(rule_line + "\n\n", style=MONO_DARK if use_color else "")

    last_idx = len(MANIFESTO_LETTER_PARAGRAPHS) - 1
    for idx, para in enumerate(MANIFESTO_LETTER_PARAGRAPHS):
        safe_para = ascii_safe(para, unicode_ok)
        if idx == 0:
            style = f"bold {MONO_WHITE}" if use_color else ""
        elif idx == last_idx:
            style = f"bold {SIGNAL_GOLD}" if use_color else ""
        elif para in _HIGHLIGHT_PARAGRAPHS or "\n" in para:
            style = f"bold {SIGNAL_GOLD}" if (use_color and para in _HIGHLIGHT_PARAGRAPHS) else (f"bold {MONO_WHITE}" if use_color else "")
        else:
            style = MONO_LIGHT if use_color else ""

        for raw_subline in safe_para.splitlines():
            wrapped = textwrap.wrap(raw_subline, width=wrap_w) or [raw_subline]
            for wline in wrapped:
                t.append("  " + wline + "\n", style=style)
        if idx < last_idx:
            t.append("\n")

    return t


def render_opening_frame(
    comp: Composition,
    step: int = 4,
    width: int = 64,
    unicode_ok: Optional[bool] = None,
    use_color: bool = True,
) -> Text:
    """Render a staged frame of the OpenBand cinematic opening sequence."""
    if unicode_ok is None:
        unicode_ok = supports_unicode()
    t = Text(no_wrap=True, overflow="crop")
    if width <= 0:
        return t

    stage = max(1, min(4, step))
    carrier = ascii_safe(TRANSMISSION_FRAMES[(stage - 1) % len(TRANSMISSION_FRAMES)], unicode_ok)
    t.append(_center_line(carrier, width) + "\n", style=SIGNAL_GOLD if use_color else "")

    if stage >= 2:
        wm = render_wordmark(width=width, unicode_ok=unicode_ok, use_color=use_color)
        t.append(wm)
        t.append("\n")
        sub_line = ascii_safe(f"A MOVEMENT FOR FREE MEDIA  ·  {comp.slogan}", unicode_ok)
        t.append(_center_line(sub_line, width) + "\n\n", style=f"bold {SIGNAL_GOLD}" if use_color else "")
    else:
        t.append("\n" * 4)

    if stage >= 3:
        art_block = render_composition(
            comp, width=width, height=11, show_attribution=True, unicode_ok=unicode_ok, use_color=use_color
        )
        t.append(art_block)
        t.append("\n")
    else:
        t.append("\n" * 9)

    if stage >= 4:
        cap_line = ascii_safe(
            "YOUTUBE · SPOTIFY · INSTAGRAM · X · FACEBOOK · ARCHIVAL BUNDLES",
            unicode_ok,
        )
        t.append("\n" + _center_line(cap_line, width), style=MONO_MID if use_color else "")

    return t


def render_composition(
    comp: Optional[Composition] = None,
    *,
    width: int = 48,
    height: int = 11,
    greeting: Optional[str] = None,
    show_attribution: bool = True,
    show_title: bool = False,
    unicode_ok: Optional[bool] = None,
    use_color: bool = True,
) -> Text:
    """Render an Artwork + Quote (+ optional Greeting) into a Rich `Text` object with `no_wrap=True`."""
    t = Text(no_wrap=True, overflow="crop")
    if width <= 0 or height <= 0:
        return t

    if comp is None:
        comp = get_composition(0)
    if unicode_ok is None:
        unicode_ok = supports_unicode()

    quote_raw = f'"{ascii_safe(comp.quote, unicode_ok)}"'
    attr_raw = ascii_safe(comp.attribution, unicode_ok)

    if width >= 44 and height >= 9 and comp.artwork.full:
        art_lines: Sequence[str] = comp.artwork.full
    elif width >= 24 and height >= 6 and comp.artwork.compact:
        art_lines = comp.artwork.compact
    else:
        art_lines = ()

    lines_out: list[tuple[str, str]] = []

    if greeting and height >= 8:
        greet_str = ascii_safe(greeting, unicode_ok)
        lines_out.append((_center_line(greet_str, width), f"bold {MONO_WHITE}" if use_color else ""))

    if show_title and height >= 12 and comp.artwork.title:
        title_str = ascii_safe(f"[ {comp.artwork.title} ]", unicode_ok)
        lines_out.append((_center_line(title_str, width), MONO_MID if use_color else ""))

    for i, raw_line in enumerate(art_lines):
        safe_line = ascii_safe(raw_line, unicode_ok)
        centered = _center_line(safe_line, width)
        lines_out.append((centered, _art_line_style(i, len(art_lines), use_color)))

    wrap_w = max(12, width)
    wrapped_quote = textwrap.wrap(quote_raw, width=wrap_w) or [quote_raw[:width]]

    needed_for_text = len(wrapped_quote[:2]) + (1 if show_attribution else 0)
    if art_lines and len(lines_out) + needed_for_text + 1 <= height:
        lines_out.append(("", ""))

    quote_style = f"bold {MONO_WHITE}" if use_color else ""
    for qline in wrapped_quote[:2]:
        lines_out.append((_center_line(qline, width), quote_style))

    if show_attribution and len(lines_out) < height:
        attr_style = SIGNAL_GOLD if use_color else ""
        lines_out.append((_center_line(attr_raw, width), attr_style))

    lines_out = lines_out[:height]

    for idx, (line_text, style) in enumerate(lines_out):
        suffix = "\n" if idx < len(lines_out) - 1 else ""
        t.append(line_text + suffix, style=style)

    return t


def render_exit_banner(
    session_number: int = 1,
    archived_count: int = 0,
    unicode_ok: Optional[bool] = None,
) -> str:
    """Render a memorable, movement-aligned exit card printed to the terminal when OpenBand closes."""
    if unicode_ok is None:
        unicode_ok = supports_unicode()
    slogan = SLOGANS[session_number % len(SLOGANS)]
    closing = EXIT_STATEMENTS[session_number % len(EXIT_STATEMENTS)]
    stats = (
        f"SESSION #{session_number} CLOSED  ·  {archived_count} ITEM{'S' if archived_count != 1 else ''} IN COMMONS CATALOG"
        if archived_count > 0
        else f"SESSION #{session_number} CLOSED  ·  CARRIER RELEASED"
    )
    box = [
        "╭──────────────────────────────────────────────────────────────────────────╮",
        f"│  ((●)) OPENBAND  ·  {slogan:<52} │",
        "├──────────────────────────────────────────────────────────────────────────┤",
        f"│  \"{closing}\"{' ' * max(0, 69 - len(closing))} │",
        f"│  {stats:<71} │",
        "╰──────────────────────────────────────────────────────────────────────────╯",
    ]
    return "\n".join(ascii_safe(line, unicode_ok) for line in box)
