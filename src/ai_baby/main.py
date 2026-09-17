"""Cross-platform terminal onboarding and conversation loop."""

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import journal, management
from .baby import Baby, TurnConflict
from .config import Config
from .memory import MemoryError, MemoryStore
from .models import Emotion, Growth, PersonalityState, Relationship, clean_text, record, safe_output
from .providers import MockProvider
from .providers.openai_compatible import OpenAICompatibleProvider

HELP = """
直接输入即可聊天；/quit 退出（每轮自动保存）。
教学：学习：海豚是一种哺乳动物。
偏好：我喜欢草莓。 / 我不喜欢草莓。
个人资料：我住在杭州。 / 我的生日是六月一日。
关系：关系：小明是我的朋友
事件：重要事件：今天我们学会了一个新词
/status      查看成长、关系和模拟情绪
/profile     查看照顾者资料
/name 名字   更新名字
/address 称呼  更新称呼（可自由选择，无需性别推断）
/memories    查看最近 20 条有效事实
/events      查看最近 10 条重要经历
/backup      在数据目录创建一致性数据库备份
/personality 查看长期形成的个体人格（模拟状态）
/journal     巩固经历并查看最近成长日记
/export      将角色数据导出到数据目录/exports（含私人信息）
/forget ID   让指定事实失效，并清理对话和日记以避免再次想起
/confirm ID  确认候选记忆；/reject ID 忽略候选
/candidates  查看最多三条待确认记忆
/baby-name 名字  给宝宝取名
/help        查看帮助
""".strip()


def prompt_valid(prompt: str, maximum: int = 80) -> str:
    """Retry validation without losing the onboarding flow."""
    while True:
        try:
            return clean_text(input(prompt), maximum)
        except ValueError as exc:
            print(exc)


def onboarding(baby: Baby) -> None:
    print("一个新的 AI 宝宝即将出生。它是软件角色，不是真实人类。")
    name = prompt_valid("你的名字是：\n> ")
    print("请选择性别：1. 男  2. 女  3. 其他 / 不想透露")
    while (choice := input("> ").strip()) not in {"1", "2", "3"}:
        print("请输入 1、2 或 3。")
    gender = {"1": "male", "2": "female", "3": "other"}[choice]
    default_address = {"male": "爸爸", "female": "妈妈"}.get(gender, name)
    print(f"AI 宝宝：你好……我好像刚刚开始运行。你叫{name}。")
    address = input(
        f"可以叫你“{default_address}”吗？回车/可以表示同意，或输入自定义称呼：\n> "
    ).strip()
    if address in {"不", "不可以", "不要", "no", "n"}:
        address = name
    elif address in {"", "可以", "好", "同意", "yes", "y"}:
        address = default_address
    try:
        address = clean_text(address, 80)
    except ValueError:
        address = prompt_valid("请输入有效称呼：\n> ")
    profile = baby.born(name, gender, address)
    print(
        f"AI 宝宝：{profile.address}你好，我是刚出生的 AI 宝宝。我还没有多少经历，你可以慢慢教我吗？"
    )


def command(baby: Baby, text: str) -> bool:
    """Run a local command. Return false only for explicit exit."""
    name, _, argument = text.partition(" ")
    memory = baby.memory
    if name in {"/forget", "/confirm", "/reject"} and (
        not argument.isascii() or not argument.isdecimal() or not 0 < int(argument) < 2**63
    ):
        raise ValueError("请提供有效的正整数记忆 ID；先用 /memories 或 /candidates 查看。")
    if name in {"/quit", "/exit"}:
        with memory.transaction():
            journal.consolidate(memory, force=True)
        return False
    if name == "/help":
        print(HELP)
    elif name == "/status":
        state = {
            "growth": record(memory.load_state("growth", Growth)),
            "relationship": record(memory.load_state("relationship", Relationship)),
            "simulated_emotion": record(memory.load_state("emotion", Emotion)),
        }
        print(json.dumps(state, ensure_ascii=False, indent=2))
    elif name == "/profile":
        print(json.dumps(record(memory.profile()), ensure_ascii=False, indent=2))
    elif name == "/name":
        print("名字已更新：" + baby.change_profile(name=clean_text(argument, 80)).name)
    elif name == "/address":
        print("称呼已更新：" + baby.change_profile(address=clean_text(argument, 80)).address)
    elif name == "/memories":
        print("\n".join(f"#{f.id} {f.text()}" for f in memory.facts()) or "还没有学到事实。")
    elif name == "/events":
        print(
            "\n".join(
                f"{e['created_at']} [{e['kind']}] {e['summary']}" for e in memory.episodes(10)
            )
        )
    elif name == "/personality":
        print(
            json.dumps(
                record(memory.load_state("personality", PersonalityState)),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif name == "/journal":
        with memory.transaction():
            journal.consolidate(memory, force=True)
        print("\n".join(j["summary"] for j in journal.recent(memory)) or "还没有新的经历。")
    elif name == "/baby-name":
        baby_name = clean_text(argument, 80)
        with memory.transaction():
            memory.set_setting("baby_name", baby_name)
        print("宝宝名字已保存：" + baby_name)
    elif name == "/forget":
        print(
            "记忆已失效；历史对话和日记已清理。"
            if management.forget(memory, int(argument))
            else "没有找到有效的事实 ID。"
        )
    elif name == "/confirm":
        print(baby.name + "：" + baby.chat(f"确认记忆 {int(argument)}").text)
    elif name == "/candidates":
        rows = memory.db.execute(
            "SELECT id,kind,subject,predicate,value FROM candidates ORDER BY id DESC LIMIT 3"
        ).fetchall()
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
    elif name == "/reject":
        with memory.transaction():
            memory.db.execute("DELETE FROM candidates WHERE id=?", (int(argument),))
        print("候选已忽略。")
    elif name == "/export":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = memory.path.parent / "exports" / f"baby-{stamp}.json"
        management.export_data(memory, target)
        print(f"已导出私人角色数据（请勿公开上传）：{target}")
    elif name == "/backup":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = memory.path.parent / "backups" / f"baby-{stamp}.sqlite3"
        memory.backup(target)
        print(f"备份完成：{target}")
    else:
        print("未知命令。输入 /help 查看帮助。")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Baby / AI 宝宝养成模拟器")
    parser.add_argument("--data-dir", type=Path, help="独立宝宝数据目录")
    parser.add_argument("--env-file", type=Path, help="显式选择 .env 文件（默认当前目录）")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    memory = None
    try:
        config = Config.load(args.data_dir, args.env_file)
        provider = MockProvider() if config.provider == "mock" else OpenAICompatibleProvider(config)
        print("==============================\nAI Baby / AI 宝宝\n==============================")
        print(
            "模式：基础离线（无网络请求）"
            if config.provider == "mock"
            else "模式：外部 LLM；你的输入、资料、相关记忆和近期聊天将发送到所配置的服务。"
        )
        memory = MemoryStore(config.data_dir.resolve() / "baby.sqlite3")
        baby = Baby(memory, provider)
        print(f"数据目录：{memory.path.parent}")
        if memory.profile() is None:
            onboarding(baby)
        else:
            print(baby.name + "：" + baby.greeting())
        print("输入 /help 查看命令，/quit 退出。每轮自动保存。")
        while True:
            text = input("你 > ").strip()
            if not text:
                continue
            try:
                text = clean_text(text)
                if text.startswith("/"):
                    if not command(baby, text):
                        break
                    continue
                reply = baby.chat(text)
                if reply.warning:
                    print(safe_output(reply.warning))
                print(baby.name + "：" + reply.text)
            except (ValueError, TurnConflict) as exc:
                print(safe_output(str(exc)))
            except sqlite3.OperationalError:
                print("记忆保存失败或被另一进程占用；本轮未提交。请关闭另一实例并检查磁盘后重试。")
        print("记忆已保存，下次见。")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\n已退出。完成的对话已保存；未完成的出生流程不会创建资料。")
        return 0
    except (MemoryError, ValueError) as exc:
        print(safe_output(str(exc)))
        return 1
    except (OSError, sqlite3.Error):
        print("无法读写本地配置或数据，请检查路径、磁盘和权限。原记忆未重置。")
        return 1
    finally:
        if memory is not None:
            memory.close()
