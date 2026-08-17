on run
    set projectPath to (POSIX path of (path to home folder)) & "Desktop/codex/codex-msu2-display"
    set toggleScript to projectPath & "/toggle_codex_display.sh"

    try
        set displayState to do shell script "/bin/zsh " & quoted form of toggleScript

        if displayState is "ON" then
            display notification "USB 屏幕服务已开启" with title "Codex 显示开关"
        else if displayState is "OFF" then
            display notification "USB 屏幕服务已关闭" with title "Codex 显示开关"
        else
            display notification displayState with title "Codex 显示开关"
        end if
    on error errorMessage number errorNumber
        display dialog "切换失败（" & errorNumber & "）" & return & errorMessage buttons {"好"} default button "好" with icon stop
    end try
end run
