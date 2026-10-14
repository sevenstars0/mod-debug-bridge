# AttrType

class in mod.common.minecraftEnum

- 描述

    描述属性枚举值，用于设置与获取实体的引擎属性的当前值与最大值

- 备注
    - ABSORPTION: 伤害吸收效果的量化值，详见wiki文档：[伤害吸收](https://zh.minecraft.wiki/w/%E4%BC%A4%E5%AE%B3%E5%90%B8%E6%94%B6)
    - 各类属性值一般通过entity的json配置，如`minecraft:knockback_resistance : {"value": 100, "max": 100}`
    - 当json文件中未配置时，引擎会针对不同属性进行不同初始值、不同最大值的设置



```python
class AttrType(object):
    HEALTH = 0
    SPEED = 1
    DAMAGE = 2
    UNDERWATER_SPEED = 3
    HUNGER = 4
    SATURATION = 5
    ABSORPTION = 6
    LAVA_SPEED = 7
    LUCK = 8
    FOLLOW_RANGE = 9
    KNOCKBACK_RESISTANCE = 10
    JUMP_STRENGTH = 11
    ARMOR = 12
    ATTACK_KNOCKBACK = 13
    ATTACK_SPEED = 14
    EXPLOSION_KNOCKBACK_RESISTANCE = 15
    FLYING_SPEED = 16
    SNEAKING_SPEED = 17
    MOVEMENT_EFFICIENCY = 18
    WATER_MOVEMENT_EFFICIENCY = 19
    BLOCK_BREAK_SPEED = 20
    MINING_EFFICIENCY = 21
    SUBMERGED_MINING_SPEED = 22

``` 

