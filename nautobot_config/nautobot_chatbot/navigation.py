"""Navigation menu items for Nautobot Chatbot plugin."""

from nautobot.apps.ui import NavMenuAddButton, NavMenuGroup, NavMenuItem, NavMenuTab


menu_items = (
    NavMenuTab(
        name="AI Assistant",
        weight=100,
        groups=(
            NavMenuGroup(
                name="Chat",
                weight=100,
                items=(
                    NavMenuItem(
                        link="plugins:nautobot_chatbot:chatbot",
                        name="AI Chat",
                        permissions=[],
                        buttons=(),
                    ),
                ),
            ),
        ),
    ),
)
