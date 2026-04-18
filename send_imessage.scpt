on run argv
  tell application "Messages" to send (item 1 of argv) to chat id (item 2 of argv)
end run
