# -*- coding: utf-8 -*-
import server.extraServerApi as serverApi
from config import ModName, SERVER_PORT, ExecListener
CMD = serverApi.GetEngineCompFactory().CreateCommand(None).SetCommand

class ServerSystem(serverApi.GetServerSystemCls()):

    def __init__(self, namespace, systemName):
        super(ServerSystem, self).__init__(namespace, systemName)
        self.ListenForEvent(ModName, 'ClientSystem', 'SetCommand', self, self.OnSetCommand)
        self._srv = ExecListener(SERVER_PORT, 'DB-Server', globals())
        self._srv.start()

    def OnSetCommand(self, args):
        commands, playerId = args['command'], args['__id__']
        for command in ((commands,)if isinstance(commands, str)else commands):
            CMD(command, playerId)

    def Update(self):
        self._srv.update()

    def Destroy(self):
        self._srv.stop()