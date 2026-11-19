mod app;
mod browser;
mod clipboard;
mod config;
mod modal;
mod quickselect;
mod remote;
mod terminal;
mod ui;

use std::io::stdout;

use ratatui::crossterm::event::{DisableBracketedPaste, DisableMouseCapture, EnableBracketedPaste, EnableMouseCapture};
use ratatui::crossterm::execute;

fn restore() {
    let _ = execute!(stdout(), DisableBracketedPaste, DisableMouseCapture);
    ratatui::restore();
}

fn main() -> std::io::Result<()> {
    if std::env::args().any(|a| a == "--version" || a == "-V") {
        println!("ssh-fm {}", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    let mut terminal = ratatui::init(); // raw mode + alternate screen + panic hook
    execute!(stdout(), EnableMouseCapture, EnableBracketedPaste)?;
    let hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        restore();
        hook(info);
    }));
    let result = app::App::new().run(&mut terminal);
    restore();
    result
}
