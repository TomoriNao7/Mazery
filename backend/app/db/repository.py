#仓储层
import json
from typing import Dict, Any, Optional, List

from sqlalchemy import select,func,delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.models import (
    Script, ScriptCharacter, Clue, Game, GameMessage, Settings,
    NPCKnowledgeState, InfoPropagationLog, GameSave, now_iso,
)


# ============================================================
# 基类
# ============================================================
class BaseRepository:
    """所有Repository的基类，提供通用Session管理"""
    def __init__(self,session:AsyncSession):
        self.session=session

# ============================================================
# ScriptRepo — 剧本仓储
# ============================================================
class ScriptRepo(BaseRepository):
    """剧本CRUD操作"""
    async def create(self,data:Dict[str,Any])->Script:
        """
        创建一个新剧本

        Args:
            data: 包含剧本字段的字典，如：
                {
                    "title": "冰锥山庄",
                    "category": "modern",
                    "scene": "暴风雪山庄",
                    "player_count": 4,
                    "outline": "...",
                    "is_custom": 0
                }
        Returns:
            创建后的 Script 对象（含生成的 id）
        """
        script=Script(**data)
        self.session.add(script)
        await self.session.commit()
        await self.session.refresh(script)
        return script

    async def get(self,script_id:str,load_relation:bool=True)->Optional[Script]:
        """
        根据 ID 获取剧本（默认加载关联的角色和线索）

        Args:
            script_id: 剧本 ID
            load_relations: 是否加载 characters 和 clues 关联数据
        Returns:
            Script 对象或 None
        """
        query=select(Script).where(Script.id==script_id)

        if load_relation:
            query=query.options(
                selectinload(Script.characters),
                selectinload(Script.clues),
                selectinload(Script.games)
            )
        result=await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
            self,
            category:Optional[str]=None,
            is_custom:Optional[int]=None,
            limit:int=50,
            offset:int=0
    )->List[Script]:
        """
        列出剧本（支持过滤和分页）

        Args:
            category: 按分类过滤 (modern/ancient/republic/japanese/campus/...)
            is_custom: 按类型过滤 (0=快速生成, 1=自定义)
            limit: 返回条数上限
            offset: 偏移量（分页用）
        Returns:
            Script 列表
        """
        query=select(Script)
        if category:
            query=query.where(Script.category==category)
        if is_custom:
            query=query.where(Script.is_custom==is_custom)

        query=query.order_by(Script.created_at.desc()).offset(offset).limit(limit)
        result=await self.session.execute(query)
        return result.scalars().all()

    async def count(self,category:Optional[str]=None,is_custom:Optional[int]=None)->int:
        """统计剧本总数（配合list做分页）"""
        query=select(func.count()).select_from(Script)
        if category:
            query=query.where(Script.category==category)
        if is_custom is not None:
            query=query.where(Script.is_custom==is_custom)
        result=await self.session.execute(query)
        return result.scalar_one()

    async def delete(self,script_id:str)->bool:
        """
        删除剧本（ORM 的 cascade 会自动删除关联的角色、线索、游戏）

        Returns:
            True 表示删除成功，False 表示剧本不存在
        """
        script=await self.get(script_id,load_relation=False)
        if not script:
            return False

        await self.session.delete(script)
        await self.session.commit()
        return True

    async def update(self,script_id:str,data:Dict[str,Any])->Optional[Script]:
        """
        部分更新剧本字段（如用户修改标题、大纲等）

        Args:
            script_id: 剧本 ID
            data: 要更新的字段字典
        Returns:
            更新后的 Script 对象，或 None（剧本不存在）
        """
        script=await self.get(script_id,load_relation=False)
        if not script:
            return None

        #只更新新传入的字段
        for key,value in data.items():
            if hasattr(script,key):
                setattr(script,key,value)

        await self.session.commit()
        await self.session.refresh(script)
        return script

# ============================================================
# GameRepo — 游戏对局仓储
# ============================================================
class GameRepo(BaseRepository):
    """游戏对局 CRUD 操作"""
    async def create(self,data:Dict[str,Any])->Game:
        """
        创建一局新游戏

        Args:
            data: 包含 script_id, player_char_id 等
        Returns:
            创建的 Game 对象
        """
        game=Game(**data)
        self.session.add(game)
        await self.session.commit()
        await self.session.refresh(game)
        return game

    async def get(self, game_id: str, load_relations: bool = True) -> Optional[Game]:
        """
        根据 ID 获取游戏对局

        Args:
            game_id: 游戏 ID
            load_relations: 是否加载关联的 messages 和 npc_states
        Returns:
            Game 对象或 None
        """
        query = select(Game).where(Game.id == game_id)

        if load_relations:
            query = query.options(
                selectinload(Game.messages),
                selectinload(Game.npc_states),
                selectinload(Game.saves),
                selectinload(Game.info_logs)
            )

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
            self,
            script_id: Optional[str] = None,
            status: Optional[str] = None,
            limit: int = 50,
            offset: int = 0
    ) -> List[Game]:
        """
        列出游戏对局

        Args:
            script_id: 按剧本 ID 过滤
            status: 按状态过滤 (playing/paused/voted/completed)
            limit: 返回条数上限
            offset: 偏移量
        Returns:
            Game 列表
        """
        query = select(Game)

        if script_id:
            query = query.where(Game.script_id == script_id)
        if status:
            query = query.where(Game.status == status)

        query = query.order_by(Game.updated_at.desc()).offset(offset).limit(limit)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def count(self, script_id: Optional[str] = None, status: Optional[str] = None) -> int:
        """统计游戏对局总数"""
        query = select(func.count()).select_from(Game)
        if script_id:
            query = query.where(Game.script_id == script_id)
        if status:
            query = query.where(Game.status == status)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def update(self, game_id: str, data: Dict[str, Any]) -> Optional[Game]:
        """
        更新游戏状态（如推进幕数、更新 found_clues 等）

        Args:
            game_id: 游戏 ID
            data: 要更新的字段字典
        Returns:
            更新后的 Game 对象，或 None
        """
        game = await self.get(game_id, load_relations=False)
        if not game:
            return None

        for key, value in data.items():
            if hasattr(game, key):
                setattr(game, key, value)

        # updated_at 会自动更新（onupdate=now_iso）
        await self.session.commit()
        await self.session.refresh(game)
        return game

    async def add_message(self, game_id: str, message_data: Dict[str, Any]) -> GameMessage:
        """
        给游戏追加一条消息（聊天记录）

        Args:
            game_id: 游戏 ID
            message_data: 消息字段字典
        Returns:
            创建的 GameMessage 对象
        """
        message = GameMessage(game_id=game_id, **message_data)
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def get_messages(self, game_id: str, act: Optional[int] = None, limit: int = 100) -> List[GameMessage]:
        """
        获取游戏的消息记录

        Args:
            game_id: 游戏 ID
            act: 按幕数过滤（可选）
            limit: 返回条数上限
        Returns:
            GameMessage 列表（按 id 升序，即时间线顺序）
        """
        query = select(GameMessage).where(GameMessage.game_id == game_id)
        if act is not None:
            query = query.where(GameMessage.act == act)
        query = query.order_by(GameMessage.id.asc()).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

# ============================================================
# SettingsRepo — 系统设置仓储
# ============================================================'
class SettingsRepo(BaseRepository):
    """系统设置 KV 存储"""

    async def get(self, key: str, default: Any = None) -> Any:
        """
        获取设置值（自动反序列化 JSON）

        Args:
            key: 设置项名称
            default: 如果 key 不存在，返回此默认值
        Returns:
            解析后的 Python 对象（字符串/数字/字典/列表）
        """
        query = select(Settings).where(Settings.key == key)
        result = await self.session.execute(query)
        setting = result.scalar_one_or_none()

        if not setting:
            return default

        try:
            return json.loads(setting.value)
        except json.JSONDecodeError:
            # 如果不是合法的 JSON，当作纯字符串返回
            return setting.value

    async def set(self, key: str, value: Any) -> None:
        """
        设置设置值（自动序列化为 JSON）

        Args:
            key: 设置项名称
            value: Python 对象（字符串/数字/字典/列表）
        """
        # 将值转为 JSON 字符串
        if isinstance(value, str):
            # 如果已经是字符串，直接存（但尝试解析成 JSON）
            try:
                # 如果字符串本身是合法的 JSON 格式，保持原样
                json.loads(value)
                value_str = value
            except json.JSONDecodeError:
                # 普通字符串，包装成 JSON 字符串
                value_str = json.dumps(value, ensure_ascii=False)
        else:
            value_str = json.dumps(value, ensure_ascii=False)

        # 先查是否存在
        query = select(Settings).where(Settings.key == key)
        result = await self.session.execute(query)
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value_str
        else:
            setting = Settings(key=key, value=value_str)
            self.session.add(setting)

        await self.session.commit()

    async def delete(self, key: str) -> bool:
        """删除设置项"""
        query = delete(Settings).where(Settings.key == key)
        result = await self.session.execute(query)
        await self.session.commit()
        return result.rowcount > 0

    async def get_all(self) -> Dict[str, Any]:
        """获取所有设置（返回字典）"""
        query = select(Settings)
        result = await self.session.execute(query)
        settings = result.scalars().all()

        all_data = {}
        for s in settings:
            try:
                all_data[s.key] = json.loads(s.value)
            except json.JSONDecodeError:
                all_data[s.key] = s.value
        return all_data


# ============================================================
# NpcStateRepo — NPC 知识状态与信息传播日志仓储（TRD 六）
# ============================================================
class NpcStateRepo(BaseRepository):
    """NPCKnowledgeState 与 InfoPropagationLog 的读写。"""

    async def save_states(self, game_id: str, states: List[Dict[str, Any]]) -> None:
        """批量 upsert NPC 状态（按 game_id + npc_id）。"""
        for data in states:
            npc_id = data.get("npc_id")
            if not npc_id:
                continue
            query = select(NPCKnowledgeState).where(
                NPCKnowledgeState.game_id == game_id,
                NPCKnowledgeState.npc_id == npc_id,
            )
            row = (await self.session.execute(query)).scalar_one_or_none()
            payload = json.dumps(data, ensure_ascii=False)
            if row:
                row.known_info = data.get("known_info") and json.dumps(data["known_info"], ensure_ascii=False) or None
                row.suspicions = data.get("suspicions") and json.dumps(data["suspicions"], ensure_ascii=False) or None
                row.discoveries = data.get("discoveries") and json.dumps(data["discoveries"], ensure_ascii=False) or None
                row.emotional_state = data.get("emotional_state") and json.dumps(data["emotional_state"], ensure_ascii=False) or None
                row.current_strategy = data.get("strategy")
                row.updated_at = now_iso()
            else:
                self.session.add(NPCKnowledgeState(
                    game_id=game_id,
                    npc_id=npc_id,
                    known_info=json.dumps(data.get("known_info", []), ensure_ascii=False),
                    suspicions=json.dumps(data.get("suspicions", {}), ensure_ascii=False),
                    discoveries=json.dumps(data.get("discoveries", []), ensure_ascii=False),
                    emotional_state=json.dumps(data.get("emotional_state", {}), ensure_ascii=False),
                    current_strategy=data.get("strategy", "defensive"),
                ))
        await self.session.commit()

    async def load_states(self, game_id: str) -> List[Dict[str, Any]]:
        """读取某对局全部 NPC 状态（转为 dict，供 NpcSimulator 恢复）。"""
        query = select(NPCKnowledgeState).where(NPCKnowledgeState.game_id == game_id)
        rows = (await self.session.execute(query)).scalars().all()
        states = []
        for r in rows:
            states.append({
                "npc_id": r.npc_id,
                "public_identity": {},
                "private_knowledge": [],
                "alibi": {},
                "knowledge_boundary": [],
                "known_info": json.loads(r.known_info) if r.known_info else [],
                "suspicions": json.loads(r.suspicions) if r.suspicions else {},
                "discoveries": json.loads(r.discoveries) if r.discoveries else [],
                "emotional_state": json.loads(r.emotional_state) if r.emotional_state else {},
                "strategy": r.current_strategy or "defensive",
            })
        return states

    async def log_info(self,
                       game_id: str,
                       act: int,
                       info_type: str,
                       info_content: str,
                       source_id: Optional[str] = None,
                       recipients: Optional[List[str]] = None,
                       player_visible: Optional[str] = None) -> InfoPropagationLog:
        """写一条信息传播日志（clue_reveal/npc_speech/private_chat）。"""
        log = InfoPropagationLog(
            game_id=game_id,
            act=act,
            info_type=info_type,
            info_content=info_content,
            source_id=source_id,
            recipients=json.dumps(recipients or [], ensure_ascii=False),
            player_visible=player_visible,
        )
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log

    async def get_info_logs(self, game_id: str, act: Optional[int] = None) -> List[InfoPropagationLog]:
        query = select(InfoPropagationLog).where(InfoPropagationLog.game_id == game_id)
        if act is not None:
            query = query.where(InfoPropagationLog.act == act)
        query = query.order_by(InfoPropagationLog.id.asc())
        return list((await self.session.execute(query)).scalars().all())
