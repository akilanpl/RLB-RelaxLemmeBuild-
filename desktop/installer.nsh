; Upgrades/uninstall must release sidecar files only after a persisted clean shutdown.
!macro customCheckAppRunning
  !insertmacro IS_POWERSHELL_AVAILABLE
  !insertmacro FIND_PROCESS "${APP_EXECUTABLE_FILENAME}" $R0
  ${if} $R0 == 0
    Exec '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" --quit-for-update'
    StrCpy $R1 0
    ${Do}
      Sleep 250
      !insertmacro FIND_PROCESS "${APP_EXECUTABLE_FILENAME}" $R0
      ${if} $R0 != 0
        ${ExitDo}
      ${endif}
      IntOp $R1 $R1 + 1
      ${if} $R1 >= 120
        MessageBox MB_OK|MB_ICONEXCLAMATION "RLB is still finishing an approved write. Quit RLB from its tray and run setup again." /SD IDOK
        Abort
      ${endif}
    ${Loop}
  ${endif}
!macroend

; Preserve per-user RLB data and selected projects on normal uninstall and upgrade.
!macro customUnInstall
  ${ifNot} ${isUpdated}
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "RLB"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "com.rlb.desktop"
  ${endif}
!macroend
