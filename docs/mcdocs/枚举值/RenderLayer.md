# RenderLayer

class in mod.common.minecraftEnum

- 描述

    方块渲染时的材质类型

- 备注
    - 目前自定义方块只支持使用部分材质，具体见<a href="../../../mcguide/20-玩法开发/15-自定义游戏内容/2-自定义方块/1-JSON组件.html" rel="noopenner"> 自定义方块json组件 </a>
        由于联机大厅和apollo存在部分材质缺少定义，所以枚举值在联机大厅和apollo环境下，整体-2
        如：Blend = 5 变成 Blend = 3 ; Opaque = 6 变成 Opaque = 4，依此类推



```python
class RenderLayer(object):
    DOUBLE_SIDED = 0
    BLEND_WATER = 1
    ALPHATEST_MICRO_BLOCK = 2
    RAY_TRACED_WATER = 3
    DEFERRED_WATER = 4
    BLEND = 5
    BLEND_TO_OPAQUE = 6
    OPAQUE = 7
    LIGHT_SOURCE = 8
    OPTIONAL_ALPHATEST = 9
    ALPHATEST = 10
    SEASONS_OPAQUE = 11
    SEASONS_OPTIONAL_ALPHATEST = 12
    ALPHATEST_SINGLE_SIDE = 13
    ALPHATEST_SINGLE_SIDE_TO_OPAQUE = 14
    ENDPORTAL = 15
    BARRIER = 16
    LIGHT = 17
    STRUCTURE_VOID = 18

``` 

