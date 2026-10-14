# -*- coding: utf-8 -*-
import client.extraClientApi as clientApi
from config import CLIENT_PORT, ExecListener

CF = clientApi.GetEngineCompFactory()
levelId = clientApi.GetLevelId()
Game = CF.CreateGame(levelId)

class ClientSystem(clientApi.GetClientSystemCls()):

    def __init__(self, namespace, systemName):
        super(ClientSystem, self).__init__(namespace, systemName)
        EN, ESN = clientApi.GetEngineNamespace(), clientApi.GetEngineSystemName()
        self.ListenForEvent(EN, ESN, 'OnKeyPressInGame', self, self.OnKeyPress)
        self._srv = ExecListener(CLIENT_PORT, 'DB-Client', globals())
        self._srv.start()
        self.isTouch = CF.CreatePlayerView(levelId).GetToggleOption('INPUT_MODE')==1

    def OnKeyPress(self, args):
        if args['screenName']=='hud_screen'and args['isDown']=='1':
            key = args['key']
            if key=='192':# ` ~ 键
                self.isTouch = not self.isTouch
                Game.SimulateTouchWithMouse(self.isTouch)
                Game.SetTipMessage('调试工具： '+('触摸'if self.isTouch else'鼠标')+'模式')
            elif key=='49':# 数字1
                self.NotifyToServer('SetCommand', {'command': 'gamemode '+str(int(not Game.GetPlayerGameType(clientApi.GetLocalPlayerId())))+' @s'})
            elif key=='50':# 数字2
                self.NotifyToServer('SetCommand', {'command': ('cleanroom', 'time set noon', 'weather clear',
                'gamerule dodaylightcycle false', 'gamerule doweathercycle false')})
                Game.SetTipMessage('调试工具： 已切换测试环境')

    def Update(self):
        self._srv.update()

    def Destroy(self):
        self._srv.stop()