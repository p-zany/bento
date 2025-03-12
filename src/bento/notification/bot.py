"""
Telegram bot implementation for Bento application.
Handles user notifications and interactions for financial data processing.
"""

import datetime
import logging
import os
from typing import Any, Callable, Dict, List, Optional

import pytz
from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bento.db import db_session
from bento.db.models import PasswordRequest, PasswordRequestStatus, Subscriber

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# 用于密码输入的状态
WAITING_FOR_PASSWORD = 1


class TelegramBot:
    """
    Telegram bot for Bento application.
    Handles notifications and interactions with users.
    """

    def __init__(
        self, token: Optional[str] = None, timezone: str = "Asia/Shanghai"
    ) -> None:
        """
        Initialize the Telegram bot.

        Args:
            token: Telegram bot token. If None, will use TELEGRAM_BOT_TOKEN env var.
            timezone: Timezone for scheduled notifications.
        """
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError(
                "Telegram bot token not provided and TELEGRAM_BOT_TOKEN env var not set"
            )

        self.timezone = pytz.timezone(timezone)
        self.application = None
        self.password_callbacks: Dict[str, Callable[[str], Any]] = {}

    async def _get_subscribers(self, active_only: bool = True) -> List[Subscriber]:
        """获取订阅者列表"""
        query = db_session.query(Subscriber)
        if active_only:
            query = query.filter(Subscriber.is_active)
        return query.all()

    async def _get_subscriber_ids(self, active_only: bool = True) -> List[int]:
        """获取订阅者ID列表"""
        subscribers = await self._get_subscribers(active_only)
        return [sub.user_id for sub in subscribers]

    async def _get_or_create_subscriber(
        self,
        user_id: int,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Subscriber:
        """获取或创建订阅者"""
        subscriber = (
            db_session.query(Subscriber).filter(Subscriber.user_id == user_id).first()
        )

        if not subscriber:
            subscriber = Subscriber(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                is_active=True,
            )
            db_session.add(subscriber)
            db_session.commit()
        else:
            # 更新订阅者信息
            subscriber.last_activity_at = datetime.datetime.utcnow()
            if first_name is not None:
                subscriber.first_name = first_name
            if last_name is not None:
                subscriber.last_name = last_name
            if username is not None:
                subscriber.username = username
            db_session.commit()

        return subscriber

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /start 命令"""
        user = update.effective_user

        # 获取或创建订阅者
        subscriber = await self._get_or_create_subscriber(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

        await update.message.reply_text(
            f"你好，{subscriber.display_name}！我是 Bento 财务管理助手。\n"
            f"使用 /subscribe 来订阅通知。\n"
            f"使用 /unsubscribe 来取消订阅。\n"
            f"使用 /status 来查看当前状态。"
        )

    async def _subscribe(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """处理 /subscribe 命令"""
        user = update.effective_user

        # 获取或创建订阅者
        subscriber = await self._get_or_create_subscriber(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

        if subscriber.is_active:
            await update.message.reply_text("你已经是订阅者了！")
        else:
            subscriber.is_active = True
            db_session.commit()
            await update.message.reply_text("成功订阅！你将收到处理结果通知。")

    async def _unsubscribe(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """处理 /unsubscribe 命令"""
        user_id = update.effective_user.id

        subscriber = (
            db_session.query(Subscriber).filter(Subscriber.user_id == user_id).first()
        )

        if subscriber and subscriber.is_active:
            subscriber.is_active = False
            db_session.commit()
            await update.message.reply_text("已取消订阅。你将不再收到通知。")
        else:
            await update.message.reply_text("你尚未订阅通知。")

    async def _status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /status 命令"""
        user_id = update.effective_user.id

        subscriber = (
            db_session.query(Subscriber).filter(Subscriber.user_id == user_id).first()
        )

        if subscriber and subscriber.is_active:
            # 获取正在等待的密码请求
            pending_requests = (
                db_session.query(PasswordRequest)
                .filter(
                    PasswordRequest.subscriber_id == subscriber.id,
                    PasswordRequest.status == PasswordRequestStatus.PENDING.value,
                )
                .count()
            )

            status_message = "你当前已订阅 Bento 通知。\n"

            if pending_requests > 0:
                status_message += f"你有 {pending_requests} 个待处理的密码请求。"

            await update.message.reply_text(status_message)
        else:
            await update.message.reply_text(
                "你当前未订阅通知。使用 /subscribe 来订阅。"
            )

    async def _handle_password(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """处理密码输入"""
        user_id = update.effective_user.id
        password = update.message.text

        # 查找待处理的密码请求
        subscriber = (
            db_session.query(Subscriber).filter(Subscriber.user_id == user_id).first()
        )

        if not subscriber:
            await update.message.reply_text("你未注册为用户。请先使用 /start 命令。")
            return ConversationHandler.END

        # 检查是否有等待处理的密码回调
        request_id = None
        for req_id, callback in self.password_callbacks.items():
            # 检查数据库中是否存在该请求
            request = (
                db_session.query(PasswordRequest)
                .filter(
                    PasswordRequest.id == req_id,
                    PasswordRequest.subscriber_id == subscriber.id,
                    PasswordRequest.status == PasswordRequestStatus.PENDING.value,
                )
                .first()
            )

            if request:
                request_id = req_id
                break

        if request_id:
            callback = self.password_callbacks.pop(request_id)
            await update.message.reply_text("密码已接收，正在处理...")

            # 更新请求状态
            request = (
                db_session.query(PasswordRequest)
                .filter(PasswordRequest.id == request_id)
                .first()
            )
            if request:
                request.status = PasswordRequestStatus.FULFILLED.value
                db_session.commit()

            # 执行回调处理密码
            try:
                await callback(password)
                await update.message.reply_text("文件已成功处理！")
            except Exception as e:
                logger.error(f"处理密码时出错: {e}")
                await update.message.reply_text(f"处理文件时出错: {e}")
                # 如果处理失败，更新状态
                if request:
                    request.status = PasswordRequestStatus.FAILED.value
                    db_session.commit()

            return ConversationHandler.END
        else:
            await update.message.reply_text("没有等待处理的密码请求。")
            return ConversationHandler.END

    async def _cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """取消当前操作"""
        user_id = update.effective_user.id
        subscriber = (
            db_session.query(Subscriber).filter(Subscriber.user_id == user_id).first()
        )

        if subscriber:
            # 取消所有待处理的密码请求
            pending_requests = (
                db_session.query(PasswordRequest)
                .filter(
                    PasswordRequest.subscriber_id == subscriber.id,
                    PasswordRequest.status == PasswordRequestStatus.PENDING.value,
                )
                .all()
            )

            for request in pending_requests:
                # 从回调字典中移除
                if request.id in self.password_callbacks:
                    self.password_callbacks.pop(request.id)

                # 更新状态
                request.status = PasswordRequestStatus.EXPIRED.value

            db_session.commit()

        await update.message.reply_text("操作已取消。")
        return ConversationHandler.END

    async def send_notification(
        self, message: str, user_ids: Optional[List[int]] = None
    ) -> None:
        """
        发送通知到所有订阅者或指定用户

        Args:
            message: 要发送的消息内容
            user_ids: 可选，指定的用户ID列表。如果为None，则发送给所有活跃订阅者
        """
        if not self.application:
            logger.error("Bot application not initialized")
            return

        try:
            # 确定目标用户
            target_users = user_ids if user_ids else await self._get_subscriber_ids()

            logger.info(f"正在发送通知给 {len(target_users)} 位用户")

            for user_id in target_users:
                try:
                    await self.application.bot.send_message(
                        chat_id=user_id, text=message
                    )
                    logger.info(f"已发送通知给用户 {user_id}")

                    # 更新最后活动时间
                    subscriber = (
                        db_session.query(Subscriber)
                        .filter(Subscriber.user_id == user_id)
                        .first()
                    )
                    if subscriber:
                        subscriber.last_activity_at = datetime.datetime.utcnow()
                        db_session.commit()
                except Exception as e:
                    logger.error(f"向用户 {user_id} 发送通知失败: {e}")
        except Exception as e:
            logger.error(f"发送通知时出错: {e}")

    async def request_password(
        self,
        user_id: int,
        email_id: str,
        email_subject: str,
        attachment_index: int,
        file_name: str,
        callback: Callable[[str], Any],
    ) -> Optional[str]:
        """
        向用户请求密码

        Args:
            user_id: 用户ID
            email_id: 邮件ID
            email_subject: 邮件主题
            attachment_index: 附件索引
            file_name: 需要密码的文件名
            callback: 处理密码的回调函数

        Returns:
            请求ID，如果失败则返回None
        """
        if not self.application:
            logger.error("Bot application not initialized")
            return None

        try:
            # 获取订阅者
            subscriber = (
                db_session.query(Subscriber)
                .filter(Subscriber.user_id == user_id)
                .first()
            )

            if not subscriber:
                logger.error(f"用户 {user_id} 不存在")
                return None

            # 创建密码请求记录
            request_id = None
            try:
                password_request = PasswordRequest(
                    subscriber_id=subscriber.id,
                    email_id=email_id,
                    email_subject=email_subject,
                    attachment_index=attachment_index,
                    filename=file_name,
                    status=PasswordRequestStatus.PENDING.value,
                )

                db_session.add(password_request)
                db_session.commit()

                # 保存回调函数以便后续处理
                request_id = password_request.id
                self.password_callbacks[request_id] = callback
            except SQLAlchemyError as e:
                logger.error(f"创建密码请求记录失败: {e}")
                db_session.rollback()
                return None

            await self.application.bot.send_message(
                chat_id=user_id,
                text=f"需要密码来处理文件 '{file_name}'（来自邮件：{email_subject}）。请发送密码或使用 /cancel 取消操作。",
            )
            logger.info(f"已向用户 {user_id} 请求密码，请求ID: {request_id}")

            return request_id
        except Exception as e:
            logger.error(f"向用户 {user_id} 请求密码失败: {e}")
            return None

    def setup(self) -> None:
        """设置机器人应用和处理器"""
        # 创建应用
        self.application = Application.builder().token(self.token).build()

        # 添加基本命令处理器
        self.application.add_handler(CommandHandler("start", self._start))
        self.application.add_handler(CommandHandler("subscribe", self._subscribe))
        self.application.add_handler(CommandHandler("unsubscribe", self._unsubscribe))
        self.application.add_handler(CommandHandler("status", self._status))

        # 添加密码处理的会话处理器
        password_conv = ConversationHandler(
            entry_points=[],  # 已经不需要入口点，因为通过request_password触发
            states={
                WAITING_FOR_PASSWORD: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self._handle_password
                    )
                ]
            },
            fallbacks=[CommandHandler("cancel", self._cancel)],
        )
        self.application.add_handler(password_conv)

        # 设置上下文类型
        self.application.context_types.chat_data_factory = lambda: {}
        self.application.context_types.user_data_factory = lambda: {}

        logger.info("Telegram bot 已设置完成")

    def run(self) -> None:
        """运行机器人"""
        if not self.application:
            self.setup()

        logger.info("启动 Telegram bot...")
        self.application.run_polling()

    async def run_async(self) -> None:
        """异步运行机器人"""
        if not self.application:
            self.setup()

        logger.info("异步启动 Telegram bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

    async def stop_async(self) -> None:
        """异步停止机器人"""
        if self.application:
            logger.info("停止 Telegram bot...")
            await self.application.stop()
            await self.application.shutdown()
