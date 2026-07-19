# -*- coding: utf-8 -*-
import server.extraServerApi as serverApi
from config import SERVER_PORT, ExecListener

CF = serverApi.GetEngineCompFactory()
levelId = serverApi.GetLevelId()


class ServerSystem(serverApi.GetServerSystemCls()):

    def __init__(self, namespace, systemName):
        super(ServerSystem, self).__init__(namespace, systemName)
        self._srv = ExecListener(SERVER_PORT, 'DB-Server', globals())
        self._srv.start()

    def Update(self):
        self._srv.update()

    def Destroy(self):
        self._srv.stop()
