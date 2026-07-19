# -*- coding: utf-8 -*-
from common.mod import Mod
from config import ModName
import server.extraServerApi as serverApi
import client.extraClientApi as clientApi
@Mod.Binding(name=ModName, version='1.0.0')
class Main(object):
    @Mod.InitServer()
    def ServerInit(self):
        serverApi.RegisterSystem(ModName, 'ServerSystem', ModName + '.serverSystem.ServerSystem')
    @Mod.InitClient()
    def ClientInit(self):
        clientApi.RegisterSystem(ModName, 'ClientSystem', ModName + '.clientSystem.ClientSystem')