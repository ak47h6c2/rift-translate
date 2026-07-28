from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    term: str
    meaning: str


GLOSSARY: tuple[GlossaryEntry, ...] = (
    GlossaryEntry("gg", "good game；通常是“这局结束了/打得不错”"),
    GlossaryEntry("wp", "well played；打得好"),
    GlossaryEntry("glhf", "good luck, have fun；祝好运，玩得开心"),
    GlossaryEntry("mb", "my bad；我的问题/我的锅"),
    GlossaryEntry("gj", "good job；干得漂亮"),
    GlossaryEntry("nt", "nice try；尽力了/尝试得不错"),
    GlossaryEntry("ff", "forfeit；投降"),
    GlossaryEntry("ff15", "15 分钟投降；也可能是在抱怨局势"),
    GlossaryEntry("go next", "这局放弃，准备下一局"),
    GlossaryEntry("diff", "差距；例如 jg diff 是在说双方打野表现差距"),
    GlossaryEntry("gap", "差距很大；用法类似 diff"),
    GlossaryEntry("int", "故意送人头；也常被夸张地用来指失误很多"),
    GlossaryEntry("inting", "正在送人头/表现得像故意送"),
    GlossaryEntry("grief", "故意搞队友或严重破坏游戏体验"),
    GlossaryEntry("griefing", "故意搞队友/摆烂"),
    GlossaryEntry("troll", "乱玩、故意整活或搞队友"),
    GlossaryEntry("toxic", "言语或行为很有攻击性"),
    GlossaryEntry("flame", "喷人、指责队友"),
    GlossaryEntry("report", "举报"),
    GlossaryEntry("afk", "离开键盘/挂机"),
    GlossaryEntry("dc", "disconnect；掉线"),
    GlossaryEntry("oom", "out of mana；没蓝"),
    GlossaryEntry("ult", "ultimate；大招"),
    GlossaryEntry("summs", "summoner spells；召唤师技能"),
    GlossaryEntry("flash", "闪现"),
    GlossaryEntry("tp", "teleport；传送"),
    GlossaryEntry("ignite", "点燃"),
    GlossaryEntry("ss", "敌人从线上消失；等同于 missing/mia"),
    GlossaryEntry("mia", "missing in action；敌人不见了"),
    GlossaryEntry("roam", "游走"),
    GlossaryEntry("gank", "抓人"),
    GlossaryEntry("camp", "反复照顾/针对同一路"),
    GlossaryEntry("leash", "开局帮打野打几下野怪"),
    GlossaryEntry("invade", "入侵对方野区"),
    GlossaryEntry("counter jungle", "反野"),
    GlossaryEntry("weakside", "资源较少、主要抗压的一侧"),
    GlossaryEntry("strongside", "队伍投入资源和关注的一侧"),
    GlossaryEntry("peel", "保护后排，把突进敌人赶开"),
    GlossaryEntry("kite", "拉扯/走砍"),
    GlossaryEntry("engage", "开团"),
    GlossaryEntry("disengage", "拉开/反开/停止交战"),
    GlossaryEntry("pick", "抓单"),
    GlossaryEntry("facecheck", "无视野直接探草或走进危险区域"),
    GlossaryEntry("vision", "视野"),
    GlossaryEntry("ward", "眼位/插眼"),
    GlossaryEntry("sweeper", "扫描饰品"),
    GlossaryEntry("shove", "快速推线"),
    GlossaryEntry("push", "推线/推进"),
    GlossaryEntry("freeze", "控线"),
    GlossaryEntry("slow push", "慢推线"),
    GlossaryEntry("crash", "把兵线推进对方防御塔"),
    GlossaryEntry("reset", "回城补给后重新出门"),
    GlossaryEntry("recall", "回城"),
    GlossaryEntry("rotate", "转线/转移支援"),
    GlossaryEntry("split", "分推"),
    GlossaryEntry("group", "抱团"),
    GlossaryEntry("siege", "推进并消耗防御塔"),
    GlossaryEntry("tempo", "节奏/行动时间差"),
    GlossaryEntry("prio", "线权/优先支援权"),
    GlossaryEntry("scale", "随等级和装备成长，偏后期"),
    GlossaryEntry("fed", "发育很好、人头和经济领先"),
    GlossaryEntry("shutdown", "终结赏金/大人头"),
    GlossaryEntry("bounty", "赏金"),
    GlossaryEntry("squishy", "身板脆、容易被秒"),
    GlossaryEntry("tank", "坦克/承伤角色"),
    GlossaryEntry("carry", "核心输出；也可指带队取胜"),
    GlossaryEntry("smurf", "高水平玩家使用低分段账号"),
    GlossaryEntry("otp", "one-trick pony；几乎只玩一个英雄的玩家"),
    GlossaryEntry("baron", "纳什男爵/大龙"),
    GlossaryEntry("drake", "元素亚龙/小龙"),
    GlossaryEntry("elder", "远古巨龙"),
    GlossaryEntry("herald", "峡谷先锋"),
    GlossaryEntry("grubs", "虚空巢虫"),
)


def find_terms(text: str, limit: int = 12) -> list[GlossaryEntry]:
    lowered = text.lower()
    matches: list[GlossaryEntry] = []
    for entry in GLOSSARY:
        pattern = rf"(?<![a-z0-9]){re.escape(entry.term.lower())}(?![a-z0-9])"
        if re.search(pattern, lowered):
            matches.append(entry)
            if len(matches) >= limit:
                break
    return matches


def compact_glossary(limit: int = 45) -> str:
    return "; ".join(f"{entry.term}={entry.meaning}" for entry in GLOSSARY[:limit])
