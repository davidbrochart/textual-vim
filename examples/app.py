from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer

from textual_vim import Vim


class MyApp(App):

    BINDINGS = [
        Binding(key="q", action="quit", description="Quit the app"),
        Binding(
            key="question_mark",
            action="help",
            description="Show help screen",
            key_display="?",
        ),
        Binding(key="delete", action="delete", description="Delete the thing"),
        Binding(key="j", action="down", description="Scroll down", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vim()
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Example Application"
        self.sub_title = "a vim-based text area"


if __name__ == "__main__":
    app = MyApp()
    app.run()
