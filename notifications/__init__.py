import abc
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class NotificationItem:
    title: str
    values: Dict[str, str]


class Notifier(abc.ABC):
    """
    Abstract base class for notification services.
    """

    @abc.abstractmethod
    def notify(
        self,
        title: str,
        content: str,
        items: Optional[List[NotificationItem]] = None,
    ) -> None:
        """
        Send a notification with the given title, content, optional accounts, and an optional table.

        Args:
            title (str): The title of the notification.
            content (str): The content/body of the notification.
            accounts (Optional[List[str]]): List of account addresses.
            items (Optional[List[NotificationItem]]): List of NotificationItem representing table rows.
        """
        pass


class DefaultNotifier(Notifier):
    """
    Default notifier that discards all notifications.
    """

    def notify(
        self,
        title: str,
        content: str,
        table: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        # Discard the notification
        pass


class SlackBotNotifier(Notifier):
    """
    Notifier implementation that sends notifications to a Slack channel via the Slack SDK.
    """

    def __init__(self, token: str, channel: str, icon_emoji: Optional[str] = None):
        """
        Args:
            token (str): The Slack bot token.
            channel (str): The Slack channel ID or name to send messages to.
            icon_emoji (Optional[str]): The emoji icon to use in Slack (not always supported).
        """
        from slack_sdk import WebClient

        self.client = WebClient(token=token)
        self.channel = channel
        self.icon_emoji = icon_emoji

    def notify(
        self,
        title: str,
        content: str,
        items: Optional[List[NotificationItem]] = None,
    ) -> None:
        """
        Send a notification to Slack with the given title, content, optional accounts, and an optional table.

        Args:
            title (str): The title of the notification.
            content (str): The content/body of the notification.
            items (Optional[List[NotificationItem]]): List of NotificationItem representing table rows.
        """
        from slack_sdk.errors import SlackApiError

        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}}]

        if content:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": content}}
            )

        if items:
            # Format as a bulleted list: each entry bolded, then indented bullets for fields
            list_md = ""
            for item in items:
                # Use the first key as the "main" label (e.g., Account)
                list_md += f"*{item.title}*\n"
                for k, value in item.values.items():
                    list_md += f"- *{k}:* {value}\n"
                list_md += "\n"
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": list_md.strip()}}
            )

        try:
            kwargs = {
                "channel": self.channel,
                "blocks": blocks,
                "text": title,
                "unfurl_links": False,
            }
            self.client.chat_postMessage(**kwargs)
        except SlackApiError as e:
            logger.error(f"Failed to send Slack notification: {e.response['error']}")
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")


def get_notifier() -> Notifier:
    """
    Factory function to get a Notifier instance based on environment variables.

    Returns:
        Notifier: An instance of a Notifier subclass.
    """
    import os

    notifier_type = os.getenv("NOTIFIER_TYPE", "default").lower()
    if notifier_type == "slack":
        token = os.getenv("SLACK_BOT_TOKEN")
        channel = os.getenv("SLACK_CHANNEL")
        icon_emoji = os.getenv("SLACK_ICON_EMOJI")
        if not token or not channel:
            raise ValueError(
                "SLACK_BOT_TOKEN and SLACK_CHANNEL must be set for Slack notifications."
            )
        return SlackBotNotifier(token=token, channel=channel, icon_emoji=icon_emoji)
    else:
        return DefaultNotifier()
