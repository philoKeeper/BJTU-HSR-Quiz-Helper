# -*- coding: utf-8 -*-
"""高铁答题助手 —— 绿色版入口。

首次运行会在同目录生成 config.json，请填写自己的学号/密码。
程序只从本目录读取题库 bank.json，不联网获取任何外部服务。
"""
import json
import os
import random
import sys
import time
from datetime import datetime

import hsr_bank as bankmod
import hsr_client as client

DEFAULT_DELAY_MIN = 5         # 提交前随机等待区间（秒），模拟真人
DEFAULT_DELAY_MAX = 9

APP_TITLE = "高铁答题助手"


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def res_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", base_dir())
    return base_dir()


CONFIG_PATH = os.path.join(base_dir(), "config.json")
BANK_PATH = os.path.join(res_dir(), "bank.json")


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def ask_credentials(prev=None):
    """让用户输入账号密码；直接回车表示沿用原值。"""
    prev = prev or {}
    print("\n----- 设置登录信息（直接回车 = 保持原值）-----")
    u_hint = "[%s]" % prev["username"] if prev.get("username") else ""
    p_hint = "[已设置，回车不变]" if prev.get("password") else ""
    username = input("学号/账号%s: " % u_hint).strip() or prev.get("username", "")
    password = input("密码%s: " % p_hint).strip() or prev.get("password", "")
    if not username or not password:
        print("账号和密码不能为空。")
        return ask_credentials(prev)
    cfg = {"username": username, "password": password}
    save_config(cfg)
    print("已保存到 %s" % CONFIG_PATH)
    return cfg


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            if cfg.get("username") and cfg.get("password"):
                return cfg
            print("config.json 里账号或密码为空，请重新填写。")
        except Exception as e:
            print("config.json 读取失败（%s），请重新填写。" % e)
    print("\n首次使用，请填写登录信息（只保存在本机 config.json）")
    return ask_credentials()


def login_loop(cfg):
    """登录；失败时允许当场改账号密码重试。返回 (token, cfg)。"""
    while True:
        print("\n正在登录（账号 %s）..." % cfg["username"])
        try:
            token = client.login(cfg["username"], cfg["password"], verbose=False)
            print("登录成功。")
            return token, cfg
        except Exception as e:
            print("登录失败：%s" % e)
            ans = input("是否修改账号/密码后重试？(y/n)：").strip().lower()
            if ans not in ("y", "yes", "是"):
                return None, cfg
            cfg = ask_credentials(cfg)


def parse_time(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except ValueError:
            continue
    return None


def status_text(rec):
    now = datetime.now()
    start, end = parse_time(rec.get("examStartTime")), parse_time(rec.get("examEndTime"))
    left = int(rec.get("participateStrategy") or 0) - int(rec.get("participateCount") or 0)
    if end and now > end:
        return "已截止"
    if start and now < start:
        return "未开始"
    if left <= 0:
        return "次数用完"
    return "可作答（剩余 %d 次）" % left


def show_list(recs):
    print("\n%-3s %-26s %-12s %-10s %s" % ("#", "章节", "已用/总", "最高分", "状态"))
    print("-" * 78)
    for i, r in enumerate(recs, 1):
        print("%-3d %-26s %-12s %-10s %s" % (
            i, str(r.get("chapterName") or "")[:24],
            "%s/%s" % (r.get("participateCount"), r.get("participateStrategy")),
            r.get("finalScore") if r.get("finalScore") is not None else "-",
            status_text(r)))
    print()


def build_answers(paper, bank):
    rows = []
    for i, q in enumerate(paper.get("questionList") or []):
        options = q.get("optionList") or []
        multi = str(q.get("multiFlag")) == "1" or str(q.get("questionType")) == "1"
        item, score, method = bankmod.lookup_item(bank, q.get("content") or "")
        trace = []
        if item and item.get("answer_options"):
            codes = bankmod.resolve_answer_options(item["answer_options"], options, multi=multi, trace=trace)
        else:
            codes = bankmod.resolve_answer(item["a"], options, multi=multi) if item else []
        # 有答案没按文本匹配上、只能靠字母兜底 → 标记出来（选项顺序被打乱时可能错）
        fallback = bool(trace) and not all(trace)
        rows.append({"q": q, "multi": multi, "codes": codes, "method": method,
                     "score": score, "fallback": fallback})
    return rows


def human_pause(delay):
    """提交前停顿，模拟真人答题，避免秒交被判定异常。"""
    if delay <= 0:
        return
    print("\n作答中，%d 秒后自动提交..." % delay)
    for left in range(delay, 0, -1):
        print("  %d" % left, end="", flush=True)
        time.sleep(1)
    print("  提交")


def delay_range_from_config(cfg):
    """返回 (最小秒, 最大秒)。兼容旧的固定值 submit_delay。"""
    if isinstance(cfg.get("submit_delay"), (int, float)):
        v = max(0, int(cfg["submit_delay"]))
        return v, v
    lo = int(cfg.get("submit_delay_min", DEFAULT_DELAY_MIN))
    hi = int(cfg.get("submit_delay_max", DEFAULT_DELAY_MAX))
    if hi < lo:
        lo, hi = hi, lo
    return max(0, lo), max(0, hi)


def take_exam(token, rec, bank, delay_range=(DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX)):
    print("\n正在进入《%s》..." % rec.get("chapterName"))
    pre = client.post("/exam/startPreCheck/%s" % rec["id"], {}, token)
    if pre.get("code") != 200:
        print("预检失败：%s" % (pre.get("msg") or pre.get("code")))
        return
    paper = client.start_exam(token, rec["id"])
    print("试卷已生成：%s，共 %d 题" % (paper.get("examName"), len(paper.get("questionList") or [])))

    rows = build_answers(paper, bank)
    missing = [r for r in rows if not r["codes"]]
    print("题库命中：%d/%d" % (len(rows) - len(missing), len(rows)))
    if missing:
        for r in missing:
            print("  未命中：%s" % (r["q"].get("content") or "")[:60])
    risky = [r for r in rows if r.get("fallback")]
    if risky:
        print("⚠ 有 %d 题的答案没能按选项原文匹配，已按字母兜底（选项顺序若被打乱可能选错）：" % len(risky))
        for r in risky:
            print("   %s" % (r["q"].get("content") or "")[:60])

    payload = {
        "hasSubmitted": False,
        "questionList": paper.get("questionList") or [],
        "answerList": [],
        "examName": paper.get("examName"),
        "duration": paper.get("duration"),
        "examCode": paper.get("examCode"),
        "examDesc": paper.get("examDesc"),
        "candidateCode": paper.get("candidateCode"),
        "examId": rec["id"],
        "examPaperId": paper.get("examPaperId"),
        "personalExamId": paper.get("id"),
    }
    base = paper.get("answerList") or []
    for i, r in enumerate(rows):
        item = dict(base[i]) if i < len(base) else {}
        item["optionCode"] = ",".join(r["codes"]) if r["multi"] else (r["codes"][0] if r["codes"] else "")
        item["optionsCodeList"] = None
        payload["answerList"].append(item)

    lo, hi = delay_range
    human_pause(random.randint(lo, hi))

    res = client.commit_exam(token, payload)
    if res.get("code") == 200:
        print("\n提交成功，得分：%s" % (res.get("data") or {}).get("totalScore"))
    else:
        print("\n提交失败：%s" % (res.get("msg") or res.get("code")))


def main():
    print("=" * 60)
    print("  " + APP_TITLE)
    print("=" * 60)
    cfg = load_config()

    try:
        bank = bankmod.load_bank(BANK_PATH)
    except Exception as e:
        print("题库读取失败：%s" % e)
        return
    print("题库：%d 题" % len(bank["items"]))

    token, cfg = login_loop(cfg)
    if not token:
        print("\n已退出。")
        return

    while True:
        try:
            recs = client.exam_list(token).get("records") or []
        except Exception as e:
            print("读取考试列表失败：%s" % e)
            input("\n按回车退出...")
            return

        show_list(recs)
        print("当前账号：%s（输入 c 可修改账号密码）" % cfg["username"])
        choice = input("输入序号开始答题，r 刷新，c 改账号，q 退出：").strip().lower()
        if choice in ("q", "quit", "exit"):
            break
        if choice in ("r", ""):
            continue
        if choice in ("c", "account", "改账号"):
            cfg = ask_credentials(cfg)
            token, cfg = login_loop(cfg)
            if not token:
                print("\n已退出。")
                return
            continue
        if not choice.isdigit() or not (1 <= int(choice) <= len(recs)):
            print("序号无效。")
            continue

        rec = recs[int(choice) - 1]
        st = status_text(rec)
        if "可作答" not in st:
            print("该考试当前不可作答：%s" % st)
            continue
        print("\n即将开始《%s》，这会消耗 1 次作答机会。" % rec.get("chapterName"))
        confirm = input("确认请输入 yes：").strip().lower()
        if confirm != "yes":
            print("已取消。")
            continue
        take_exam(token, rec, bank, delay_range_from_config(cfg))
        input("\n按回车返回列表...")

    print("再见。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出。")
