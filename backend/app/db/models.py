#ORM模型
from datetime import datetime
import uuid
from typing import Optional, List

from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.database import Base


def gen_id()->str:
    return uuid.uuid4().hex[:16]

def now_iso() -> str:
    """返回当前时间的ISO格式字符串"""
    return datetime.now().isoformat()

# ============================================================
# 剧本表（scripts）
# ============================================================
class Script(Base):
    __tablename__ = "scripts"

    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=gen_id)#剧本编号
    title:Mapped[str]=mapped_column(String(255),nullable=False,default="未命名剧本")#剧本标题
    category:Mapped[str]=mapped_column(String(32),nullable=False)#剧本分类
    scene:Mapped[str]=mapped_column(String(100),nullable=False)#剧本场景
    player_count:Mapped[int]=mapped_column(Integer,nullable=False,default=6)#游玩人数
    outline:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#用户大纲（自定义模式）
    full_script:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#AI生成的完整剧本 Json
    summary:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#剧本简介（书架/详情弹窗）
    is_saved:Mapped[int]=mapped_column(Integer,nullable=False,default=0)#是否在本地剧本库 1=是
    is_custom:Mapped[int]=mapped_column(Integer,nullable=False,default=0)#是否为自定义模式 0=自动 1=自定义
    created_at:Mapped[str]=mapped_column(String(25),default=now_iso)#创建时间戳

    #关系
    characters:Mapped[List["ScriptCharacter"]]=relationship(
        back_populates="script",
        cascade="all, delete-orphan"
    )
    clues:Mapped[List["Clue"]]=relationship(
        back_populates="script",
        cascade="all, delete-orphan"
    )
    games:Mapped[List["Game"]]=relationship(
        back_populates="script",
        cascade="all, delete-orphan"
    )

# ============================================================
# 角色表（script_characters）
# ============================================================
class ScriptCharacter(Base):
    __tablename__ = "script_characters"

    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=gen_id)#角色编号
    script_id:Mapped[str]=mapped_column(String(36),ForeignKey("scripts.id",ondelete="CASCADE"),nullable=False)#剧本编号
    name:Mapped[str]=mapped_column(String(50),nullable=False)#角色名称
    gender:Mapped[str]=mapped_column(String(10),nullable=False)# 性别
    age:Mapped[int]=mapped_column(Integer,nullable=False)#年龄
    personality:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#性格
    background:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#公开背景（L1）
    secret:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#隐藏秘密（L3）
    is_murderer:Mapped[int]=mapped_column(Integer,default=0)#是否是凶手 1=凶手
    is_player:Mapped[int]=mapped_column(Integer,default=0)#是否是真人玩家 0=AI 1=真人
    portrait_prompt:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#AI生图，角色立绘提示词

    script:Mapped["Script"]=relationship(back_populates="characters")

# ============================================================
# 线索表（clues）
# ============================================================
class Clue(Base):
    __tablename__ = "clues"

    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=gen_id)#线索编号
    script_id:Mapped[str]=mapped_column(String(36),ForeignKey("scripts.id",ondelete="CASCADE"),nullable=False)#剧本编号
    name:Mapped[str]=mapped_column(String(100),nullable=False)#线索名称
    description:Mapped[str]=mapped_column(Text,nullable=False)#线索描述
    location:Mapped[Optional[str]]=mapped_column(String(100),nullable=True)#线索位置
    is_key:Mapped[int]=mapped_column(Integer,default=0)#是否是关键线索 1=直接指向真凶的证据链环节 0=误导线索
    difficulty:Mapped[str]=mapped_column(String(10),nullable=False,default="easy")#发现难度 easy/medium/hard
    act:Mapped[Optional[int]]=mapped_column(Integer,nullable=True)#线索所属幕数（线索提前泄露校验用）
    points_to:Mapped[Optional[str]]=mapped_column(String(36),nullable=True)#指向的角色id，可为真凶也可为误导
    found:Mapped[int]=mapped_column(Integer,default=0)#是否被找到

    script: Mapped["Script"] = relationship(back_populates="clues")

# ============================================================
# 游戏对局表（games）
# ============================================================
class Game(Base):
    __tablename__ = "games"

    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=gen_id)#对局编号
    script_id:Mapped[str]=mapped_column(String(36),ForeignKey("scripts.id",ondelete="CASCADE"),nullable=False)#剧本编号
    status:Mapped[str]=mapped_column(String(16),default="playing")#对局状态 playing/paused/voted/completed
    current_act:Mapped[int]=mapped_column(Integer,default=1)#当前幕数
    player_char_id:Mapped[Optional[str]]=mapped_column(String(36),nullable=True)#玩家选择的角色id
    game_log:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#完整游戏日志
    found_clues:Mapped[Optional[str]]=mapped_column(Text,nullable=True)#已发现线索id列表（Json）
    created_at:Mapped[str]=mapped_column(String(25),default=now_iso)#对局创建时间
    updated_at:Mapped[str]=mapped_column(String(25),default=now_iso)#最后更新时间

    script:Mapped["Script"]=relationship(back_populates="games")
    messages:Mapped[List["GameMessage"]]=relationship(
        back_populates="game",
        cascade="all, delete-orphan"
    )
    npc_states:Mapped[List["NPCKnowledgeState"]]=relationship(
        back_populates="game",
        cascade="all, delete-orphan"
    )
    info_logs:Mapped[List["InfoPropagationLog"]]=relationship(
        back_populates="game",
        cascade="all, delete-orphan"
    )
    saves:Mapped[List["GameSave"]]=relationship(
        back_populates="game",
        cascade="all, delete-orphan"
    )

# ============================================================
# 消息记录表（game_messages）
# ============================================================
class GameMessage(Base):
    __tablename__ = "game_messages"

    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement= True)#id升序排列，聊天记录时间线
    game_id:Mapped[str]=mapped_column(String(36),ForeignKey("games.id",ondelete="CASCADE"),nullable=False)#所属对局id
    act:Mapped[Optional[int]]=mapped_column(Integer,nullable=True)#所属幕数
    role:Mapped[str]=mapped_column(String(16),nullable=False)#消息来源角色类型 narrator：旁白 player：玩家 character_xxx：具体npc
    speaker_name:Mapped[Optional[str]]=mapped_column(String(50),nullable=True)#角色名称
    content:Mapped[str]=mapped_column(Text,nullable=False)#消息正文
    action_type:Mapped[Optional[str]]=mapped_column(String(32),nullable=True)#行动类型 narration：纯文本居中 dialogue：对话气泡 search：搜证结果 accuse：指控 vote：投票 system：系统消息
    created_at:Mapped[str]=mapped_column(String(25),default=now_iso)#创建时间

    game:Mapped["Game"]=relationship(back_populates="messages")

# ============================================================
# 系统设置表（settings）
# ============================================================
class Settings(Base):
    __tablename__ = "settings"

    key:Mapped[str]=mapped_column(String(64),primary_key=True)#设置项名称
    value:Mapped[str]=mapped_column(Text,nullable=False)#设置项值（Json字符串）
    updated_at:Mapped[str]=mapped_column(String(25),default=now_iso,onupdate=now_iso)

# ============================================================
# NPC 知识状态表（npc_knowledge_states）
# ============================================================
class NPCKnowledgeState(Base):
    __tablename__ = "npc_knowledge_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)#
    game_id: Mapped[str] = mapped_column(String(36), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    npc_id: Mapped[str] = mapped_column(String(36), nullable=False)          # 对应 script_characters.id
    known_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON: 当前npc已知信息列表
    suspicions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON: {npc_id: 怀疑程度}
    discoveries: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: npc自己发现的线索 ID 列表
    emotional_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: {stress, trust, fear, anger} 情绪状态
    current_strategy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: {type, target} 当前策略
    updated_at: Mapped[str] = mapped_column(String(25), default=now_iso, onupdate=now_iso)

    # 关系
    game: Mapped["Game"] = relationship(back_populates="npc_states")

# ============================================================
# 信息传播日志表（info_propagation_logs）
# ============================================================
class InfoPropagationLog(Base):
    __tablename__ = "info_propagation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String(36), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    act: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)#发生在第几幕
    info_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # clue_reveal/npc_speech/private_chat 消息类型
    info_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)#消息内容
    source_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)#消息来源
    recipients: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON: 收到信息的 NPC ID 列表
    player_visible: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 玩家看到的表象描述
    created_at: Mapped[str] = mapped_column(String(25), default=now_iso)

    # 关系
    game: Mapped["Game"] = relationship(back_populates="info_logs")

# ============================================================
# 历史游玩表（play_history）—— 历史游玩剧本库，7 天自动清除
# ============================================================
class PlayHistory(Base):
    __tablename__ = "play_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    script_id: Mapped[str] = mapped_column(String(36), ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    last_played_at: Mapped[str] = mapped_column(String(25), default=now_iso)   # 最近游玩时间

    script: Mapped["Script"] = relationship()

# ============================================================
# 游戏存档表（game_saves）
# ============================================================
class GameSave(Base):
    __tablename__ = "game_saves"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    game_id: Mapped[str] = mapped_column(String(36), ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    save_data: Mapped[str] = mapped_column(Text, nullable=False)              # JSON: 完整游戏状态快照
    created_at: Mapped[str] = mapped_column(String(25), default=now_iso)

    # 关系
    game: Mapped["Game"] = relationship(back_populates="saves")

