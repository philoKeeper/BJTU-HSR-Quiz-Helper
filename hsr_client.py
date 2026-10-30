"""59.64.5.158 答题系统 API 客户端（含自动滑块验证码）。

写操作（startExam / commit）全部需要显式调用，默认不触发。
"""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

import hsr_aes as aes

BASE = "http://59.64.5.158/prod-api"
HERE = os.path.dirname(os.path.abspath(__file__))


class ApiError(RuntimeError):
    def __init__(self, msg, payload=None):
        super().__init__(msg)
        self.payload = payload or {}


def _request(method, path, payload=None, token=None, timeout=40):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=utf-8"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except Exception:
            return {"code": e.code, "msg": body[:300]}


def get(path, token=None, **kw):
    return _request("GET", path, None, token, **kw)


def post(path, payload, token=None, **kw):
    return _request("POST", path, payload, token, **kw)


# ---------------------------------------------------------------- captcha
def solve_offset(orig_b64, piece_b64):
    """纯 PIL 模板匹配（不依赖 numpy，方便打包）。

    返回拼图块左边缘在背景图上的像素 x。
    """
    orig = Image.open(io.BytesIO(base64.b64decode(orig_b64))).convert("RGB")
    piece = Image.open(io.BytesIO(base64.b64decode(piece_b64))).convert("RGBA")
    bbox = piece.getchannel("A").getbbox()
    if not bbox:
        raise ApiError("验证码拼图块为空")
    bx0, by0, bx1, by1 = bbox
    patch = piece.crop(bbox)
    pw, ph = patch.size
    pdata = list(patch.getdata())
    pts = [(i, j, p[0], p[1], p[2])
           for j in range(ph) for i in range(pw)
           for p in (pdata[j * pw + i],) if p[3] > 8]
    if not pts:
        raise ApiError("验证码拼图块无有效像素")

    W, H = orig.size
    odata = list(orig.getdata())
    abs_y = by0 if piece.size[1] == H else None
    y_range = [abs_y] if abs_y is not None else range(0, H - ph + 1)

    best_s, best_x, best_y = 1e9, 0, abs_y or 0
    n = len(pts)
    for y in y_range:
        for x in range(0, W - pw + 1):
            total = 0
            for i, j, pr, pg, pb in pts:
                q = odata[(y + j) * W + x + i]
                total += abs(q[0] - pr) + abs(q[1] - pg) + abs(q[2] - pb)
            s = total / n
            if s < best_s:
                best_s, best_x, best_y = s, x, y
    return best_x, best_y, best_s


def solve_captcha(max_try=4, verbose=False):
    """返回 (code_for_login, debug_info)。失败抛 ApiError。"""
    last = None
    for i in range(max_try):
        cap = post("/captcha/get", {"captchaType": "blockPuzzle"})
        if cap.get("repCode") != "0000":
            last = cap
            time.sleep(0.5)
            continue
        d = cap["repData"]
        x, y, score = solve_offset(d["originalImageBase64"], d["jigsawImageBase64"])
        point_json = json.dumps({"x": int(x), "y": 5}, separators=(",", ":"))
        enc = aes.aes_ecb_encrypt_b64(point_json.encode(), d["secretKey"])
        chk = post("/captcha/check", {
            "captchaType": "blockPuzzle",
            "pointJson": enc,
            "token": d["token"],
        })
        if verbose:
            print("    captcha x=%s sad=%.2f check=%s" % (x, score, chk.get("repCode")))
        if chk.get("repCode") == "0000":
            verification = aes.aes_ecb_encrypt_b64(
                (d["token"] + "---" + point_json).encode(), d["secretKey"])
            return verification, {"x": x, "sad": score}
        last = chk
        time.sleep(0.4)
    raise ApiError("验证码多次未通过: %s" % last, last)


def login(username, password, verbose=True):
    code, dbg = solve_captcha(verbose=verbose)
    res = post("/login", {"username": username, "password": password, "code": code, "uuid": ""})
    if not res.get("token"):
        raise ApiError("登录失败: %s" % res.get("msg"), res)
    if verbose:
        print("  登录成功 %s" % res.get("msg", ""))
    return res["token"]


# ---------------------------------------------------------------- exam
def exam_list(token, **params):
    q = {"pageNumber": 1, "pageSize": 100}
    q.update(params)
    r = get("/exam/my?" + urllib.parse.urlencode(q), token)
    # 该接口返回裸分页对象（records/rows），不带 code
    if "records" in r or "rows" in r:
        return r
    if r.get("code") == 200:
        return r
    raise ApiError("读取考试列表失败: %s" % r.get("msg"), r)


def start_exam(token, exam_id):
    """⚠ 会消耗一次考试机会，并生成个人试卷。"""
    r = post("/exam/startExam/%s" % exam_id, {}, token)
    if r.get("code") != 200:
        raise ApiError("开始考试失败: %s" % r.get("msg"), r)
    return r.get("data")


def save_exam(token, payload):
    return post("/exam/save", payload, token)


def commit_exam(token, payload):
    return post("/exam/commit", payload, token)


def detail_answer(token, personal_exam_id):
    # 前端调用方式是 params={id: personalExamId}
    r = get("/exam/detailAnswer?id=%s" % personal_exam_id, token)
    if r.get("code") != 200:
        raise ApiError("读取答卷详情失败: %s" % r.get("msg"), r)
    return r.get("data")


if __name__ == "__main__":
    print("client module")
