/////////////////////////////////////////////////////////////////////////
///@author 东方财富证券股份有限公司
///@file quote_sze_define.h
///@brief 定义深交所行情输出结构
/////////////////////////////////////////////////////////////////////////
#pragma once
#include <string.h>

/// 深交所exchange_id
#define        SZE_EXCHANGE_ID                  (101)
/// 深交所合约长度
#define        SZE_SYMBOL_LEN                   (9)
/// 深交所快照深度
#define        SZE_LEV2_DEPTH                   (10)
/// 深交所ibr 建树深度
#define        SZE_IBR_DEPTH                    (5)

/// 深交所快照消息类型
#define        SZE_LEV2_SNAP_MSG_TYPE           (21)
/// 深交所指数消息类型
#define        SZE_LEV2_IDX_MSG_TYPE            (22)
/// 深交所订单消息类型
#define        SZE_LEV2_ORDER_MSG_TYPE          (23)
/// 深交所成交消息类型
#define        SZE_LEV2_EXE_MSG_TYPE            (24)
/// 深交所盘后定价消息类型
#define        SZE_LEV2_AF_CLOSE_MSG_TYPE       (25)
/// 深交所建树消息类型
#define        SZE_LEV2_TREE_MSG_TYPE           (29)
/// 深交所IBR建树快照
#define        SZE_LEV2_IBR_TREE_MSG_TYPE       (28)
/// 深交所成交量统计快照
#define        SZE_LEV2_TURNOVER_MSG_TYPE       (26)
/// 深交所债券快照消息类型
#define        SZE_LEV2_BOND_SNAP_MSG_TYPE      (80)
/// 深交所债券逐笔委托消息类型
#define        SZE_LEV2_BOND_ORDER_MSG_TYPE     (81)
/// 深交所债券逐笔成交消息类型
#define        SZE_LEV2_BOND_EXE_MSG_TYPE       (82)

/// 深交所快照心跳消息类型,api内部消化
#define        SZE_LEV2_SNAP_HT_MSG_TYPE        (121)
/// 深交所指数心跳消息类型,api内部消化
#define        SZE_LEV2_IDX_HT_MSG_TYPE         (122)
/// 深交所逐笔消息心跳消息类型,api内部消化
#define        SZE_LEV2_TICK_HT_MSG_TYPE        (123)
/// 深交所盘后定价心跳消息类型,api内部消化
#define        SZE_LEV2_AF_CLOSE_HT_MSG_TYPE    (125)
/// 深交所全新快照心跳消息类型,api内部消化
#define        SZE_LEV2_TREE_HT_MSG_TYPE        (129)
/// 深交所IBR建树快照心跳消息类型,api内部消化
#define        SZE_LEV2_IBR_TREE_HT_MSG_TYPE    (128)
/// 深交所成交量统计快照心跳消息类型,api内部消化
#define        SZE_LEV2_TURNOVER_HT_MSG_TYPE    (126)
/// 深交所债券快照心跳消息类型,api内部消化
#define        SZE_LEV2_BOND_SNAP_HT_MSG_TYPE   (180)
/// 深交所债券逐笔心跳消息类型,api内部消化
#define        SZE_LEV2_BOND_TICK_HT_MSG_TYPE   (181)


#pragma pack(push, 1)

/////////////////////////////////////////////////////////////////////////
///@brief EMQSzeTickType 深交所逐笔数据类型
/////////////////////////////////////////////////////////////////////////
typedef enum EMQSzeTickType {
    kTickTypeOrder,     ///< 逐笔委托
    kTickTypeExe,       ///< 逐笔成交
    kTickTypeBondOrder, ///< 债券逐笔委托
    kTickTypeBondExe,   ///< 债券逐笔成交
} EMQSzeTickType;

/// 深交所快照档位单元
struct EMQSzePriceQuantityUnit
{
    /// 限价单和市价单都参与建树,对于建树行情,订单价格取值方法如下表：
    ///  |订单类型 \ 买卖方向 |                    买（1）          |                           卖（2）                  |
    ///  |     市价（1）      |                    卖一价           |                           买一价                   |
    ///  |     限价（2）      |   如果小于 3 的取为 3，否则取原值   |   如果大于 999999997，取为 999999997，否则取原值   |
    ///  |    本方最优(U）    |                    买一价           |                           卖一价                   |

    /// 价格，实际值需要除以 10000
    unsigned int                      m_price;
    /// 数量，实际值需要除以 100
    unsigned long long                m_quantity;
};

/// 深交所心跳消息
struct EMQSzeHeartbeat
{
    /// 行情序号
    unsigned int                      m_sequence;
    /// 保留字段
    unsigned int                      m_reserved_1;
    /// 行情类型
    unsigned char                     m_message_type;
    /// 保留字段
    unsigned char                     m_reserved_2[7];
};

/// 深交所消息协议头
struct EMQSzeHead
{
    /// 行情序号
    unsigned int                      m_sequence;
    /// 保留字段
    unsigned int                      m_reserved_1;
    /// 行情类型
    unsigned char                     m_message_type;
    /// 0:指数 1:股票 2:基金 3:债券 4:回购 5:权证 6:期货 7:外汇 8:利率 9:期权 10:其他

    /// 证券类型
    unsigned char                     m_security_type;
    /// 当 security_type == 0 时, 恒为0
    /// 当 security_type == 1 时，0：主板 1：中小板 2：创业板 3：B股 4：H股 5：科创版 255:未分类
    /// 当 security_type == 2 时，248：LOF基金 249：ETF基金 255：未分类
    /// 当 security_type == 3 时，248：国债 249：可转债 255：未分类
    /// 当 security_type == 4 时，248：国债回购 255：未分类
    /// 当 security_type == 5/6/7/8/10时，255:没有意义
    /// 当 security_type == 9 时，248：股票期权 249：ETF期权 255：未分类

    /// 证券子类型
    unsigned char                     m_sub_security_type;
    /// 证券代码
    unsigned char                     m_symbol[SZE_SYMBOL_LEN];
    /// 交易所编号
    unsigned char                     m_exchange_id;
    /// 格式如：YYYYMMDDHHMMSSsss（毫秒）
    /// YYYY=0000-9999, MM=01-12,    DD=01-31, HH=00-23, MM=00-59, SS=00-60(秒)，sss=000-999(毫秒)。

    /// 行情更新时间
    unsigned long long                m_quote_update_time;
    /// 频道号
    unsigned short                    m_channel_num;
    /// 包序号
    unsigned long long                m_sequence_num;
    /// 行情类别
    unsigned int                      m_md_stream_id;
};

/// 深交所快照消息
struct EMQSzeSnap
{
    EMQSzeSnap()
    {
        memset(this, 0, sizeof(EMQSzeSnap));
    }

    /// 包头
    EMQSzeHead                        m_head;
    /// * | Bit 位    | 返回值 | 交易所值 | 描述                                 |
    /// * | --------- | ------ | -------- | ------------------------------------ |
    /// * | Bid7-Bid4 | 0      | 'S'      | 表示启动(开市前)                     |
    /// * |           | 1      | 'O'      | 表示开盘集合竞价                     |
    /// * |           | 2      | 'T'      | 表示连续交易                         |
    /// * |           | 3      | 'B'      | 表示休市                             |
    /// * |           | 4      | 'C'      | 表示收盘集合竞价                     |
    /// * |           | 5      | 'E'      | 表示已闭市                           |
    /// * |           | 6      | 'H'      | 表示临时停牌                         |
    /// * |           | 7      | 'A'      | 表示盘后交易                         |
    /// * |           | 8      | 'V'      | 表示波动性中断                       |
    /// * |           | 15     | other    | 表示无意义                           |
    /// * | Bit3      | 0      | '0'      | 表示此正常状态                       |
    /// * |           | 1      | '1'      | 表示全天停牌                         |
    /// * |           | 0      | other    | 表示无意义，当成此产品可正常交易处理 |
    /// * | Bit2      | 0      |          | 预留位，值为 0                       |
    /// * | Bit1      | 0      |          | 预留位，值为 0                       |
    /// * | Bit0      | 0      |          | 预留位，值为 0                       |

    /// 交易状态码
    unsigned char                     m_trading_status;
    /// 成交笔数
    unsigned long long                m_total_trade_num;
    /// 总成交量，          实际值需要除以 100
    unsigned long long                m_total_quantity;
    /// 总成交额，          实际值需要除以 1000000
    unsigned long long                m_total_value;
    /// 昨收价，            实际值需要除以 10000
    unsigned int                      m_pre_close_price;
    /// 最新价，            实际值需要除以 10000
    unsigned int                      m_last_price;
    /// 开盘价，            实际值需要除以 10000
    unsigned int                      m_open_price;
    /// 最高价，实际值需要除以 10000
    unsigned int                      m_day_high_price;
    /// 最低价，实际值需要除以 10000
    unsigned int                      m_day_low_price;
    /// 收盘价，实际值需要除以 10000
    unsigned int                      m_today_close_price;
    /// 买方挂单均价，实际值需要除以 10000
    unsigned int                      m_total_bid_weighted_avg_price;
    /// 买总量，实际值需要除以 100
    unsigned long long                m_total_bid_quantity;
    /// 卖方挂单均价，实际值需要除以 10000
    unsigned int                      m_total_ask_weighted_avg_price;
    /// 卖总量，实际值需要除以 100
    unsigned long long                m_total_ask_quantity;
    /// 基金 T-1 日净值，实际值需要除以 10000
    unsigned int                      m_lpv;
    /// 基金实时参考净值，实际值需要除以 10000
    unsigned int                      m_iopv;
    /// 涨停价，实际值需要除以 10000
    unsigned int                      m_upper_limit_price;
    /// 跌停价，实际值需要除以 10000
    unsigned int                      m_low_limit_price;
    /// 合约持仓量，实际值需要除以 10000
    unsigned int                      m_open_interest;
    /// 买方十档
    EMQSzePriceQuantityUnit      m_bid_unit[SZE_LEV2_DEPTH];
    /// 卖方十档
    EMQSzePriceQuantityUnit      m_ask_unit[SZE_LEV2_DEPTH];

    /// 当 Ask_1_Qty=0 时，TotalAskQty 重置为 0；当 Bid_1_Qty=0 时，TotalBidQty 重置为 0。
};

/// 深交所指数消息
struct EMQSzeIdx
{
    EMQSzeIdx()
    {
        memset(this, 0, sizeof(EMQSzeIdx));
    }

    /// 包头
    EMQSzeHead                        m_head;
    /// 成交笔数
    unsigned long long                m_total_trade_num;
    /// 总成交量，实际值需要除以 100
    unsigned long long                m_total_quantity;
    /// 总成交额，实际值需要除以 1000000
    unsigned long long                m_total_value;
    /// 最新价，实际值需要除以 10000
    unsigned int                      m_last_price;
    /// 昨收价，实际值需要除以 10000
    unsigned int                      m_pre_close_price;
    /// 开盘价，实际值需要除以 10000
    unsigned int                      m_open_price;
    /// 最高价，实际值需要除以 10000
    unsigned int                      m_day_high_price;
    /// 最低价，实际值需要除以 10000
    unsigned int                      m_day_low_price;
    /// 收盘价，实际值需要除以 10000
    unsigned int                      m_today_close_price;
    /// 保留字段
    char                              m_reserved[5];
};

/// 深交所订单消息
struct EMQSzeTickOrder
{
    EMQSzeTickOrder()
    {
        memset(this, 0, sizeof(EMQSzeTickOrder));
    }
    /// 包头
    EMQSzeHead                        m_head;
    /// 对逐笔委托价格转换说明如下：
    ///  |订单类型 \ 买卖方向 |                    买（1）            |                           卖（2）                    |
    ///  |     市价（1）      |                    直接透传           |                           直接透传                   |
    ///  |    本方最优(U）    |                    直接透传           |                           直接透传                   |
    ///  |     限价（2）      |   如果小于 3 的取为 3，否则取原值     |   如果大于 999999997，取为 999999997，否则取原值     |

    /// 价格，  实际值需要除以 10000
    unsigned int                      m_order_price;
    /// 数量，  实际值需要除以 100
    unsigned long long                m_order_quantity;
    /// 方向 ‘1’=买 ‘2’=卖
    char                              m_side_flag;
    /// 订单类型 '1'=市价  '2'=限价  'U'=本方最优
    char                              m_order_type;
    /// 保留字段
    char                              m_reserved[15];
};

/// 深交所成交消息
struct EMQSzeTickExe
{
    EMQSzeTickExe()
    {
        memset(this, 0, sizeof(EMQSzeTickExe));
    }

    /// 包头
    EMQSzeHead                        m_head;
    /// 买方包序号
    long long                         m_trade_buy_num;
    /// 卖方包序号
    long long                         m_trade_sell_num;
    /// 价格，   实际值需要除以 10000
    unsigned int                      m_trade_price;
    /// 数量，   实际值需要除以 100
    long long                         m_trade_quantity;
    /// 成交类型 '4'=撤销  'F'=成交
    char                              m_trade_type;
};

/// 深交所逐笔行情
struct EMQSzeTick
{
    /// 深交所逐笔数据类型
    EMQSzeTickType m_tick_type;
    union {
        /// 深交所逐笔委托
        EMQSzeTickOrder *m_tick_order;
        /// 深交所逐笔成交
        EMQSzeTickExe *m_tick_exe;
    };
};

/// 深交所建树消息
struct EMQSzeTree
{
    /// 初始化结构体
    EMQSzeTree()
    {
        memset(this, 0, sizeof(EMQSzeTree));
    }

    /// 包头
    EMQSzeHead                        m_head;
    /// 成交笔数
    long long                         m_total_trade_num;
    /// 总成交量，实际值需要除以 100
    unsigned long long                m_total_quantity;
    /// 总成交额，实际值需要除以 1000000
    long long                         m_total_value;
    /// 昨收价，实际值需要除以 10000
    unsigned int                      m_pre_close_price;
    /// 最新价，实际值需要除以 10000
    unsigned int                      m_last_price;
    /// 开盘价，实际值需要除以 10000
    unsigned int                      m_open_price;
    /// 最高价，实际值需要除以 10000
    unsigned int                      m_day_high_price;
    /// 最低价，实际值需要除以 10000
    unsigned int                      m_day_low_price;
    /// 收盘价，实际值需要除以 10000
    unsigned int                      m_today_close_price;
    /// 买方挂单均价，实际值需要除以 10000
    unsigned int                      m_total_bid_weighted_avg_price;
    /// 买总量，实际值需要除以 100
    unsigned long long                m_total_bid_quantity;
    /// 卖方挂单均价，实际值需要除以 10000
    unsigned int                      m_total_ask_weighted_avg_price;
    /// 卖总量，实际值需要除以 100
    unsigned long long                m_total_ask_quantity;
    /// 涨停价，实际值需要除以 10000
    unsigned int                      m_upper_limit_price;
    /// 跌停价，实际值需要除以 10000
    unsigned int                      m_low_limit_price;
    /// Bid 边市价单挂单总量，实际值需要除以 100
    unsigned long long                m_market_open_total_bid;
    /// Ask 边市价单挂单总量，实际值需要除以 100
    unsigned long long                m_market_open_total_ask;
    /// Bid 边总档位数
    unsigned int                      m_bid_depth;
    /// Ask 边总档位数
    unsigned int                      m_ask_depth;
    /// 买方十档
    EMQSzePriceQuantityUnit           m_bid_unit[SZE_LEV2_DEPTH];
    /// 卖方十档
    EMQSzePriceQuantityUnit           m_ask_unit[SZE_LEV2_DEPTH];
    /// 0x01=此消息前逐笔消息有断号发生；0x00=逐笔消息序号连续，正常；
    char                              m_ch_gap_flag;
    /// 保留字段
    char                              m_reserved[4];
};

/// 深交债券快照消息
struct EMQSzeBondSnap
{
    /// 初始化结构体
    EMQSzeBondSnap()
    {
        memset( this , 0 , sizeof( EMQSzeBondSnap ) );
    }
    /// 包头
    EMQSzeHead                   m_head;

    /// * | Bit 位    | 返回值 | 交易所值 | 描述                                 |
    /// * | --------- | ------ | -------- | ------------------------------------ |
    /// * | Bid7-Bid4 | 0      | 'S'      | 表示启动(开市前)                     |
    /// * |           | 1      | 'O'      | 表示开盘集合竞价                     |
    /// * |           | 2      | 'T'      | 表示连续交易                         |
    /// * |           | 3      | 'B'      | 表示休市                             |
    /// * |           | 4      | 'C'      | 表示收盘集合竞价                     |
    /// * |           | 5      | 'E'      | 表示已闭市                           |
    /// * |           | 6      | 'H'      | 表示临时停牌                         |
    /// * |           | 7      | 'A'      | 表示盘后交易                         |
    /// * |           | 8      | 'V'      | 表示波动性中断                       |
    /// * |           | 15     | other    | 表示无意义                           |
    /// * | Bit3      | 0      | '0'      | 表示此正常状态                       |
    /// * |           | 1      | '1'      | 表示全天停牌                         |
    /// * |           | 0      | other    | 表示无意义，当成此产品可正常交易处理 |
    /// * | Bit2      | 0      |          | 预留位，值为 0                       |
    /// * | Bit1      | 0      |          | 预留位，值为 0                       |
    /// * | Bit0      | 0      |          | 预留位，值为 0                       |

    /// 交易状态码
    unsigned char                     m_trading_status;
    /// 成交笔数
    unsigned long long                m_total_trade_num;
    /// 总成交量，实际值需要除以 100
    unsigned long long                m_total_quantity;
    /// 总成交额，实际值需要除以 1000000
    unsigned long long                m_total_value;
    /// 昨收价，实际值需要除以 10000
    unsigned int                      m_pre_close_price;
    /// 最新价，实际值需要除以 10000
    unsigned int                      m_last_price;
    /// 开盘价，实际值需要除以 10000
    unsigned int                      m_open_price;
    /// 最高价，实际值需要除以 10000
    unsigned int                      m_day_high_price;
    /// 最低价，实际值需要除以 10000
    unsigned int                      m_day_low_price;
    /// 收盘价，实际值需要除以 10000
    unsigned int                      m_today_close_price;
    /// 加权平均价，实际值需要除以 10000
    unsigned int                      m_total_trade_weighted_avg_price;
    /// 升跌 1, 实际值需要除以 10000
    int                               m_fluctuation_1;
    /// 升跌 2, 实际值需要除以 10000
    int                               m_fluctuation_2;
    /// 买方挂单均价，实际值需要除以 10000
    unsigned int                      m_total_bid_weighted_avg_price;
    /// 买总量，实际值需要除以 100
    unsigned long long                m_total_bid_quantity;
    /// 卖方挂单均价，实际值需要除以 10000
    unsigned int                      m_total_ask_weighted_avg_price;
    /// 卖总量，实际值需要除以 100
    unsigned long long                m_total_ask_quantity;

    /// 加权平均涨跌 BP 实际值需要除以 10000
    int                               m_weighted_avg_price_BP;
    /// 昨收盘加权平均价 实际值需要除以 10000
    unsigned int                      m_weighted_avg_pre_close_price;
    /// 匹配成交最新价 实际值需要除以 10000
    unsigned int                      m_auction_trade_last_price;
    /// 保留字段
    unsigned char                     m_reserved[4];
    /// 匹配成交成交量 实际值需要除以 100
    unsigned long long                m_auction_volume_trade;
    /// 匹配成交成交金额 实际值需要除以 1000000
    unsigned long long                m_auction_value_trade;

    /// 买方十档
    EMQSzePriceQuantityUnit           m_bid_unit[SZE_LEV2_DEPTH];
    /// 卖方十档
    EMQSzePriceQuantityUnit           m_ask_unit[SZE_LEV2_DEPTH];
};

/// 深交所债券逐笔委托
struct EMQSzeBondOrder
{
    EMQSzeBondOrder()
    {
        memset( this , 0 , sizeof( EMQSzeBondOrder ) );
    }
    /// 包头
    EMQSzeHead                        m_head;
    /// 对逐笔委托价格转换说明如下：
    ///  |订单类型 \ 买卖方向 |                    买（1）            |                           卖（2）                    |
    ///  |     市价（1）      |                    直接透传           |                           直接透传                   |
    ///  |    本方最优(U）    |                    直接透传           |                           直接透传                   |
    ///  |     限价（2）      |   如果小于 3 的取为 3，否则取原值     |   如果大于 999999997，取为 999999997，否则取原值     |

    /// 价格，实际值需要除以 10000
    unsigned int                      m_price;
    /// 数量，实际值需要除以 100
    unsigned long long                m_quantity;
    /// 方向，‘1’=买 ‘2’=卖
    char                              m_side;
    /// 订单类型 '1'=市价  '2'=限价  'U'=本方最优
    char                              m_order_type;
    /// 保留字段
    char                              m_reserved[15];
};

/// 深交所债券逐笔成交
struct EMQSzeBondExe
{
    EMQSzeBondExe()
    {
        memset( this , 0 , sizeof( EMQSzeBondExe ) );
    }
    /// 包头
    EMQSzeHead                        m_head;
    /// 买方包序号
    long long                         m_buy_num;
    /// 卖方包序号
    long long                         m_sell_num;
    /// 价格，实际值需要除以 10000
    unsigned int                      m_price;
    /// 数量，实际值需要除以 100
    long long                         m_quantity;
    /// 成交类型 '4'=撤销  'F'=成交
    char                              m_type;
};

/// 深交所债券逐笔行情
struct EMQSzeBondTick
{
    /// 深交所逐笔数据类型
    EMQSzeTickType m_tick_type;
    union {
        /// 深交所债券逐笔委托
        EMQSzeBondOrder *m_bond_order;
        /// 深交所债券逐笔成交
        EMQSzeBondExe *m_bond_exe;
    };
};

#pragma pack(pop)
