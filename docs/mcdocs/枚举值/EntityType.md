# EntityType

class in mod.common.minecraftEnum

- 描述

    实体类型枚举

- 备注
    - 当实体行为包内使用[runtime_identifier](https://dev.mc.163.com/dev/mcmanual/mc-dev/mconline/15-%E7%8E%A9%E6%B3%95%E7%BB%84%E4%BB%B6%E6%95%99%E7%A8%8B/7-%E8%87%AA%E5%AE%9A%E4%B9%89%E5%AE%9E%E4%BD%93/4-%E6%8E%A2%E7%B4%A2%E5%AE%9E%E4%BD%93%E7%9A%84%E8%A1%8C%E4%B8%BA%E6%96%87%E4%BB%B6.html#%E7%90%86%E8%A7%A3%E5%AE%9E%E4%BD%93%E8%A1%8C%E4%B8%BA%E7%9A%84%E6%8F%8F%E8%BF%B0%E4%BF%A1%E6%81%AF)字段继承某种实体的特征时，此时实体所属分类与runtime_indentifier所指向的实体相同。
    - 自定义实体未使用runtime_identifier字段时该实体默认只属于Mob类。
    - 在控制台打印枚举值为位运算结果，例如，EntityType.Zombie 输出为 199456。



```python
class EntityType(object):
    Undefined = 1
    TypeMask = 255
    Mob = 256
    PathfinderMob = 512 | Mob
    Monster = 2048 | PathfinderMob
    Animal = 4096 | PathfinderMob
    TamableAnimal = 16384 | Animal
    Ambient = 32768 | Mob
    UndeadMob = 65536 | Monster
    ZombieMonster = 131072 | UndeadMob
    Arthropod = 262144 | Monster
    Minecart = 524288
    SkeletonMonster = 1048576 | UndeadMob
    EquineAnimal = 2097152 | TamableAnimal
    Projectile = 4194304
    AbstractArrow = 8388608
    WaterAnimal = 8192 | PathfinderMob
    VillagerBase = 16777216 | PathfinderMob
    Chicken = 10 | Animal
    Cow = 11 | Animal
    Pig = 12 | Animal
    Sheep = 13 | Animal
    Wolf = 14 | TamableAnimal
    Villager = 15 | VillagerBase
    MushroomCow = 16 | Animal
    Squid = 17 | WaterAnimal
    Rabbit = 18 | Animal
    Bat = 19 | Ambient
    IronGolem = 20 | PathfinderMob
    SnowGolem = 21 | PathfinderMob
    Ocelot = 22 | TamableAnimal
    Horse = 23 | EquineAnimal
    PolarBear = 28 | Animal
    Llama = 29 | Animal
    Parrot = 30 | TamableAnimal
    Dolphin = 31 | WaterAnimal
    Donkey = 24 | EquineAnimal
    Mule = 25 | EquineAnimal
    SkeletonHorse = 26 | EquineAnimal | UndeadMob
    ZombieHorse = 27 | EquineAnimal | UndeadMob
    Zombie = 32 | ZombieMonster
    Creeper = 33 | Monster
    Skeleton = 34 | SkeletonMonster
    Spider = 35 | Arthropod
    PigZombie = 36 | UndeadMob
    Slime = 37 | Monster
    EnderMan = 38 | Monster
    Silverfish = 39 | Arthropod
    CaveSpider = 40 | Arthropod
    Ghast = 41 | Monster
    LavaSlime = 42 | Monster
    Blaze = 43 | Monster
    ZombieVillager = 44 | ZombieMonster
    Witch = 45 | Monster
    Stray = 46 | SkeletonMonster
    Husk = 47 | ZombieMonster
    WitherSkeleton = 48 | SkeletonMonster
    Guardian = 49 | Monster
    ElderGuardian = 50 | Monster
    Npc = 51 | Mob
    WitherBoss = 52 | UndeadMob
    Dragon = 53 | Monster
    Shulker = 54 | Monster
    Endermite = 55 | Arthropod
    Agent = 56 | Mob
    Vindicator = 57 | Monster
    Phantom = 58 | UndeadMob
    IllagerBeast = 59 | Monster
    ArmorStand = 61 | Mob
    TripodCamera = 62 | Mob
    Player = 63 | Mob
    ItemEntity = 64
    PrimedTnt = 65
    FallingBlock = 66
    MovingBlock = 67
    ExperiencePotion = 68 | Projectile
    Experience = 69
    EyeOfEnder = 70
    EnderCrystal = 71
    FireworksRocket = 72
    Trident = 73 | Projectile | AbstractArrow
    Turtle = 74 | Animal
    Cat = 75 | TamableAnimal
    ShulkerBullet = 76 | Projectile
    FishingHook = 77
    Chalkboard = 78
    DragonFireball = 79 | Projectile
    Arrow = 80 | Projectile | AbstractArrow
    Snowball = 81 | Projectile
    ThrownEgg = 82 | Projectile
    Painting = 83
    LargeFireball = 85 | Projectile
    ThrownPotion = 86 | Projectile
    Enderpearl = 87 | Projectile
    LeashKnot = 88
    WitherSkull = 89 | Projectile
    BoatRideable = 90
    WitherSkullDangerous = 91 | Projectile
    LightningBolt = 93
    SmallFireball = 94 | Projectile
    AreaEffectCloud = 95
    LingeringPotion = 101 | Projectile
    LlamaSpit = 102 | Projectile
    EvocationFang = 103 | Projectile
    EvocationIllager = 104 | Monster
    Vex = 105 | Monster
    MinecartRideable = 84 | Minecart
    MinecartHopper = 96 | Minecart
    MinecartTNT = 97 | Minecart
    MinecartChest = 98 | Minecart
    MinecartFurnace = 99 | Minecart
    MinecartCommandBlock = 100 | Minecart
    IceBomb = 106 | Projectile
    Balloon = 107
    Pufferfish = 108 | WaterAnimal
    Salmon = 109 | WaterAnimal
    Drowned = 110 | ZombieMonster
    Tropicalfish = 111 | WaterAnimal
    Fish = 112 | WaterAnimal
    Panda = 113 | Animal
    Pillager = 114 | Monster
    VillagerV2 = 115 | VillagerBase
    ZombieVillagerV2 = 116 | ZombieMonster
    Shield = 117
    WanderingTrader = 118 | PathfinderMob
    Lectern = 119
    ElderGuardianGhost = 120 | Monster
    Fox = 121 | Animal
    Bee = 122 | Mob
    Piglin = 123 | Mob
    Hoglin = 124 | Animal
    Strider = 125 | Animal
    Zoglin = 126 | UndeadMob
    PiglinBrute = 127 | Mob
    Goat = 128 | Animal
    GlowSquid = 129 | WaterAnimal
    Axolotl = 130 | Animal
    Warden = 131 | Monster
    Frog = 132 | Animal
    Tadpole = 133 | WaterAnimal
    Allay = 134 | Mob
    ChestBoatRideable = 136 | BoatRideable
    TraderLlama = 137 | Llama
    Camel = 138 | Animal
    Sniffer = 139 | Animal
    Breeze = 140 | Monster
    BreezeWindChargeProjectile = 141 | Projectile
    Armadillo = 142 | Animal
    WindChargeProjectile = 143 | Projectile
    Bogged = 144 | SkeletonMonster
    OminousItemSpawner = 145
    Creaking = 146 | Monster
    HappyGhast = 147 | Animal
    CopperGolem = 148 | PathfinderMob
    Nautilus = 149 | WaterAnimal
    ZombieNautilus = 150 | WaterAnimal | UndeadMob
    Parched = 151 | SkeletonMonster
    CamelHusk = 152 | UndeadMob
    CustomProjectile = 254 | Projectile
    EntityExtension = 255
    MAX_ENTITY_ID = 256

``` 

