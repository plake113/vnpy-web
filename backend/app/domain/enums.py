"""交易领域共享枚举（业务词汇）。

来源：vnpy 4.5.0 ``vnpy/trader/constant.py``（MIT License，© Xiaoyou Chen）。
经内容梳理后，这里不按源文件机械搬运，而是作为领域层的**共享词汇模块**：

- ``Direction`` / ``Offset`` / ``Status`` / ``OrderType`` 等同时被行情、委托、
  持仓、账户与网关使用，拆散到各子领域会产生循环依赖；
- 交易场所、品种、周期等元数据也由多个子领域共用；
- 若未来某组枚举只服务单一子域，再拆出去。

与原始实现的差异：

- 使用 ``StrEnum``：``value`` 是稳定的英文机器码，供 API、数据库与前端条件判断使用；
  原实现把 gettext 翻译后的中文直接作为枚举值。中文展示名保留在 ``label`` 属性中；
- 不再依赖 ``vnpy/trader/locale``，界面文案统一交给前端 i18n；
- ``Offset.NONE`` 由空字符串 ``""`` 改为 ``"NONE"``，避免 API / 数据库出现空枚举值；
- ``Exchange`` / ``Currency`` / ``Interval`` 的成员与取值与原版完全一致，
  因为 ``vt_symbol`` 等标识由 ``exchange.value`` 拼接而来。
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "Currency",
    "Direction",
    "Exchange",
    "Interval",
    "Offset",
    "OptionType",
    "OrderType",
    "Product",
    "Status",
]


class Direction(StrEnum):
    """报单 / 成交 / 持仓方向。"""

    LONG = "LONG"
    SHORT = "SHORT"
    NET = "NET"

    @property
    def label(self) -> str:
        """中文展示名（原 vnpy 的枚举值）。"""
        return _DIRECTION_LABELS[self]


_DIRECTION_LABELS: dict[Direction, str] = {
    Direction.LONG: "多",
    Direction.SHORT: "空",
    Direction.NET: "净",
}


class Offset(StrEnum):
    """开平方向。"""

    NONE = "NONE"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSETODAY = "CLOSETODAY"
    CLOSEYESTERDAY = "CLOSEYESTERDAY"

    @property
    def label(self) -> str:
        """中文展示名（原 vnpy 的枚举值）。"""
        return _OFFSET_LABELS[self]


_OFFSET_LABELS: dict[Offset, str] = {
    Offset.NONE: "无",
    Offset.OPEN: "开",
    Offset.CLOSE: "平",
    Offset.CLOSETODAY: "平今",
    Offset.CLOSEYESTERDAY: "平昨",
}


class Status(StrEnum):
    """委托状态。"""

    SUBMITTING = "SUBMITTING"
    NOTTRADED = "NOTTRADED"
    PARTTRADED = "PARTTRADED"
    ALLTRADED = "ALLTRADED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @property
    def label(self) -> str:
        """中文展示名（原 vnpy 的枚举值）。"""
        return _STATUS_LABELS[self]

    @property
    def is_active(self) -> bool:
        """委托是否仍活跃（原 ``ACTIVE_STATUSES`` 集合语义）。"""
        return self in _ACTIVE_STATUSES


_STATUS_LABELS: dict[Status, str] = {
    Status.SUBMITTING: "提交中",
    Status.NOTTRADED: "未成交",
    Status.PARTTRADED: "部分成交",
    Status.ALLTRADED: "全部成交",
    Status.CANCELLED: "已撤销",
    Status.REJECTED: "拒单",
}

#: 仍可能继续成交、可撤销的状态；原来的模块级 ``ACTIVE_STATUSES`` 集合。
_ACTIVE_STATUSES: frozenset[Status] = frozenset(
    {Status.SUBMITTING, Status.NOTTRADED, Status.PARTTRADED}
)


class Product(StrEnum):
    """合约品种。"""

    EQUITY = "EQUITY"
    FUTURES = "FUTURES"
    OPTION = "OPTION"
    INDEX = "INDEX"
    FOREX = "FOREX"
    SPOT = "SPOT"
    ETF = "ETF"
    BOND = "BOND"
    WARRANT = "WARRANT"
    SPREAD = "SPREAD"
    FUND = "FUND"
    CFD = "CFD"
    SWAP = "SWAP"

    @property
    def label(self) -> str:
        """中文展示名（原 vnpy 的枚举值）。"""
        return _PRODUCT_LABELS[self]


_PRODUCT_LABELS: dict[Product, str] = {
    Product.EQUITY: "股票",
    Product.FUTURES: "期货",
    Product.OPTION: "期权",
    Product.INDEX: "指数",
    Product.FOREX: "外汇",
    Product.SPOT: "现货",
    Product.ETF: "ETF",
    Product.BOND: "债券",
    Product.WARRANT: "权证",
    Product.SPREAD: "价差",
    Product.FUND: "基金",
    Product.CFD: "CFD",
    Product.SWAP: "互换",
}


class OrderType(StrEnum):
    """委托类型。"""

    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"
    FAK = "FAK"
    FOK = "FOK"
    RFQ = "RFQ"
    ETF = "ETF"

    @property
    def label(self) -> str:
        """中文展示名（原 vnpy 的枚举值）。"""
        return _ORDER_TYPE_LABELS[self]


_ORDER_TYPE_LABELS: dict[OrderType, str] = {
    OrderType.LIMIT: "限价",
    OrderType.MARKET: "市价",
    OrderType.STOP: "STOP",
    OrderType.FAK: "FAK",
    OrderType.FOK: "FOK",
    OrderType.RFQ: "询价",
    OrderType.ETF: "ETF",
}


class OptionType(StrEnum):
    """期权类型。"""

    CALL = "CALL"
    PUT = "PUT"

    @property
    def label(self) -> str:
        """中文展示名（原 vnpy 的枚举值）。"""
        return _OPTION_TYPE_LABELS[self]


_OPTION_TYPE_LABELS: dict[OptionType, str] = {
    OptionType.CALL: "看涨期权",
    OptionType.PUT: "看跌期权",
}


class Exchange(StrEnum):
    """交易所 / 交易场所。

    取值与原 vnpy 完全一致（部分名称缩写与直觉不同，例如 EUREX 的值为 ``EUX``），
    因为 ``symbol.exchange.value`` 会拼进 ``vt_symbol``。
    """

    # 中国内地
    CFFEX = "CFFEX"  # 中国金融期货交易所
    SHFE = "SHFE"  # 上海期货交易所
    CZCE = "CZCE"  # 郑州商品交易所
    DCE = "DCE"  # 大连商品交易所
    INE = "INE"  # 上海国际能源交易中心
    GFEX = "GFEX"  # 广州期货交易所
    SSE = "SSE"  # 上海证券交易所
    SZSE = "SZSE"  # 深圳证券交易所
    BSE = "BSE"  # 北京证券交易所
    SHHK = "SHHK"  # 沪港通
    SZHK = "SZHK"  # 深港通
    SGE = "SGE"  # 上海黄金交易所
    WXE = "WXE"  # 无锡不锈钢电子交易中心
    CFETS = "CFETS"  # 外汇交易中心
    XBOND = "XBOND"  # 外汇交易中心 X-Bond

    # 境外
    SMART = "SMART"  # 美股智能路由
    NYSE = "NYSE"  # 纽约证券交易所
    NASDAQ = "NASDAQ"  # 纳斯达克交易所
    ARCA = "ARCA"  # 纽交所高增长板
    EDGEA = "EDGEA"  # Direct Edge 交易所
    ISLAND = "ISLAND"  # 纳斯达克 Island ECN
    BATS = "BATS"  # Bats 交易所
    IEX = "IEX"  # 投资者交易所
    AMEX = "AMEX"  # 美国证券交易所
    TSE = "TSE"  # 多伦多证券交易所
    NYMEX = "NYMEX"  # 纽约商业交易所
    COMEX = "COMEX"  # 纽约商品交易所
    GLOBEX = "GLOBEX"  # 芝加哥商业交易所 Globex
    IDEALPRO = "IDEALPRO"  # 盈透外汇 ECN
    CME = "CME"  # 芝加哥商业交易所
    ICE = "ICE"  # 洲际交易所
    SEHK = "SEHK"  # 香港联合交易所
    HKFE = "HKFE"  # 香港期货交易所
    SGX = "SGX"  # 新加坡交易所
    CBOT = "CBOT"  # 芝加哥期货交易所
    CBOE = "CBOE"  # 芝加哥期权交易所
    CFE = "CFE"  # CBOE 期货交易所
    DME = "DME"  # 迪拜商品交易所
    EUREX = "EUX"  # 欧洲期货交易所
    APEX = "APEX"  # 亚太交易所
    LME = "LME"  # 伦敦金属交易所
    BMD = "BMD"  # 马来西亚衍生品交易所
    TOCOM = "TOCOM"  # 东京商品交易所
    EUNX = "EUNX"  # 泛欧交易所
    KRX = "KRX"  # 韩国交易所
    OTC = "OTC"  # 场外交易市场
    IBKRATS = "IBKRATS"  # 盈透证券美股模拟交易所

    # 特殊用途
    LOCAL = "LOCAL"  # 本地生成数据
    GLOBAL = "GLOBAL"  # 尚未支持的具体交易所


class Currency(StrEnum):
    """币种。"""

    USD = "USD"
    HKD = "HKD"
    CNY = "CNY"
    CAD = "CAD"


class Interval(StrEnum):
    """K 线周期。"""

    MINUTE = "1m"
    HOUR = "1h"
    DAILY = "d"
    WEEKLY = "w"
    TICK = "tick"
