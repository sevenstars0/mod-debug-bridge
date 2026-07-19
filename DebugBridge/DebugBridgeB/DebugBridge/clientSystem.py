# -*- coding: utf-8 -*-
import client.extraClientApi as clientApi
from config import CLIENT_PORT, ExecListener

CF = clientApi.GetEngineCompFactory()
levelId = clientApi.GetLevelId()


class ClientSystem(clientApi.GetClientSystemCls()):

    def __init__(self, namespace, systemName):
        super(ClientSystem, self).__init__(namespace, systemName)
        self._srv = ExecListener(CLIENT_PORT, 'DB-Client', globals())
        self._srv.start()

    def Update(self):
        self._srv.update()

    def Destroy(self):
        self._srv.stop()
