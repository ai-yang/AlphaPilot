/////////////////////////////////////////////////////////////////////////
///@author 东方财富证券股份有限公司
///@file quote_sse_define.h
///@brief 定义上交所行情输出结构
/////////////////////////////////////////////////////////////////////////
#pragma once
#include <string.h>

/// 上交所exchange_id
#define        SSE_EXCHANGE_ID                  (100)
/// 上交所合约长度
#define        SSE_SYMBOL_LEN                   (9)
/// 上交所lev2档位深度
#define        SSE_LEV2_DEPTH                   (10)
/// 上交所期权档位深度
#define        SSE_OPTION_DEPTH                 (5)
/// 上交所证券代码长度
#define        SSE_SECURITY_NAME_LEN            (9)
/// 上交所产品状态长度
#define        SSE_PRODUCT_STATUS_LEN           (21)
/// 日期长度
#define        DATE_LEN                         (9)

/// 上交所lev2指数消息类型
#define        SSE_LEV2_IDX_MSG_TYPE            (33)
/// 上交所lev2成交消息类型
#define        SSE_LEV2_EXE_MSG_TYPE            (34)
/// 上交所lev2期权消息类型
#define        SSE_LEV2_OPT_MSG_TYPE            (35)
/// 上交所lev2快照消息类型
#define        SSE_LEV2_SNAP_MSG_TYPE           (39)
/// 上交所lev2委托信息类型
#define        SSE_LEV2_ORDER_MSG_TYPE          (32)
/// 上交所lev2建树信息类型
#define        SSE_LEV2_TREE_MSG_TYPE           (38)
/// 上交所lev2债券快照信息类型
#define        SSE_LEV2_BOND_SNAP_MSG_TYPE      (60)
/// 上交所lev2债券逐笔信息类型
#define        SSE_LEV2_BOND_TICK_MSG_TYPE      (61)
/// 上交所lev2逐笔合并信息类型
#define        SSE_LEV2_TICK_MERGE_MSG_TYPE     (62)
/// 上交所lev2 ETF 信息类型
#define        SSE_LEV2_ETF_MSG_TYPE            (63)
/// 上交所lev2静态信息类型
#define        SSE_LEV2_STATIC_INFO_MSG_TYPE    (255)

/// 上交所lev2指数心跳消息类型，api内部消化
#define        SSE_LEV2_IDX_HT_MSG_TYPE         (133)
/// 上交所lev2逐笔心跳信息类型，api内部消化
#define        SSE_LEV2_TICK_HT_MSG_TYPE        (132)
/// 上交所lev2期权心跳信息类型，api内部消化
#define        SSE_LEV2_OPT_HT_MSG_TYPE         (135)
/// 上交所lev2建树心跳信息类型，api内部消化
#define        SSE_LEV2_TREE_HT_MSG_TYPE        (138)
/// 上交所lev2快照心跳信息类型，api内部消化
#define        SSE_LEV2_SNAP_HT_MSG_TYPE        (139)
/// 上交所lev2债券快照心跳信息类型，api内部消化
#define        SSE_LEV2_BOND_SNAP_HT_MSG_TYPE   (160)
/// 上交所lev2债券逐笔心跳信息类型，api内部消化
#define        SSE_LEV2_BOND_TICK_HT_MSG_TYPE   (161)
/// 上交所lev2逐笔合并心跳信息类型，api内部消化
#define        SSE_LEV2_TICK_MERGE_HT_MSG_TYPE  (162)
/// 上交所lev2 ETF 心跳信息类型，api内部消化
#define        SSE_LEV2_ETF_HT_MSG_TYPE         (163)


#pragma pack(push, 1)

/// 上交所心跳消息
struct EMQSseHeartbeat
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

/// 上交所消息协议头
struct EMQSseHead
{
    /// 行情序号
    unsigned int                      m_sequence;
    /// 保留字段
    unsigned int                      m_reserved_1;
    /// 行情类型
    unsigned char                     m_message_type;
    /// 包括此消息头的长度
    unsigned short                    m_message_len;
    /// 交易所编号
    unsigned char                     m_exchange_id;
    /// 行情更新年份
    unsigned short                    m_quote_date_year;
    /// 行情更新月份
    unsigned char                     m_quote_date_month;
    /// 行情更新日期
    unsigned char                     m_quote_date_day;
    /// 交易所发送时间
    unsigned int                      m_send_time;
    /// 数据产品类别
    unsigned char                     m_category_id;
    /// 行情包序号
    unsigned int                      m_msg_seq_id;
    /// 1=有丢包，0=没有丢包
    unsigned char                     m_seq_lost_flag;
};

/// 上交所lev2快照档位单元
struct EMQSseL2PriceQuantityUnit
{
    /// 保留字段
    char                              m_reserved[4];
    /// 价格，实际值需要除以 1000
    unsigned int                      m_price;
    /// 数量，实际值需要除以 1000
    unsigned long long                m_quantity;
};

/// 上交所lev2快照消息
struct EMQSseSnap
{
    EMQSseSnap()
    {
        memset(this, 0, sizeof(EMQSseSnap));                          // 初始化结构体
    }

    /// 包头
    EMQSseHead                   m_head;
    /// 行情更新时间，格式如：HHMMSS（秒）HH=00-23, MM=00-59, SS=00-59（秒）
    unsigned int                      m_quote_update_time;
    /// 证券代码
    char                              m_symbol[SSE_SYMBOL_LEN];
    /// 证券类型：0=指数，1=股票，2=基金，3=债券，4=回购，5=权证，6=期货，7=外汇，8=利率，9=期权，10=其他
    unsigned char                     m_security_type;
    /// 快照类型，1=全量，2=更新
    unsigned char                     m_image_status;
    /// 保留字段
    unsigned char                     m_reserved_1;
    /// 昨收价，实际值需要除以 1000
    unsigned int                      m_pre_close_price;
    /// 开盘价，实际值需要除以 1000
    unsigned int                      m_open_price;
    /// 最高价，实际值需要除以 1000
    unsigned int                      m_day_high_price;
    /// 最低价，实际值需要除以 1000
    unsigned int                      m_day_low_price;
    /// 最新价，实际值需要除以 1000
    unsigned int                      m_last_price;
    /// 收盘价，实际值需要除以 1000
    unsigned int                      m_today_close_price;
    /// 当前品种交易状态
    /// 当前产品状态：0=其他，1=启动，2=开市集合竞价，3=连续自动撮合，4=停牌，5=收盘集合竞价，6=闭市自动计算闭市价格，7=交易结束，8=产品未上市
    unsigned char                     m_instrument_status;
    /// Bit7-Bit4(m_trading_status&0xF0):
    /// 0x00:表示启动（开市前)
    /// 0x10:表示开盘集合竞价
    /// 0x20:表示连续交易
    /// 0x30:表示闭市
    /// 0x40:表示合约停牌
    /// 0x50:表示可恢复交易的熔断时段（盘中集合竞价）
    /// 0x60:表示不可恢复交易的熔断时段（暂停交易至闭市）
    /// 0x70:表示收盘集合竞价时段
    /// 0x80:表示波动性中断（适用于股票期权)
    /// 0x15:表示无意义
    /// Bit3(m_trading_status&0x08):
    /// 0x08:‟表示此合约可正常交易 0x00:表示此合约不可正常交易
    /// Bit2(m_trading_status&0x04):
    /// 0x04:表示已上市 0x00:表示未上市
    /// Bit1(m_trading_status&0x02):
    /// 0x02:表示此合约在当前时段接受订单申报 0x00:表示此合约在当前时段不接受订单申报
    /// Bit0:预留
    unsigned char                     m_trading_status;
    /// 保留字段
    unsigned short                    m_reserved_2;
    /// 成交笔数
    unsigned int                      m_total_trade_num;
    /// 成交总量，实际值需要除以 1000
    unsigned long long                m_total_quantity;
    /// 成交总额，实际值需要除以 100000
    unsigned long long                m_total_value;
    /// 委托买入总量，实际值需要除以 1000
    unsigned long long                m_total_bid_quantity;
    /// 买方加权平均委买价格，实际值需要除以 1000
    unsigned int                      m_total_bid_weighted_avg_price;
    /// 委托卖出总量，实际值需要除以 1000
    unsigned long long                m_total_ask_quantity;
    /// 卖方加权平均委买价格，实际值需要除以 1000
    unsigned int                      m_total_ask_weighted_avg_price;
    /// IOPV高精度值
    unsigned int                      m_IOPV;
    /// 买盘价位数量
    unsigned char                     m_bid_depth;
    /// 卖盘价位数量
    unsigned char                     m_ask_depth;
    /// 买边十档
    EMQSseL2PriceQuantityUnit         m_bid_unit[SSE_LEV2_DEPTH];
    /// 卖边十档
    EMQSseL2PriceQuantityUnit         m_ask_unit[SSE_LEV2_DEPTH];
};

/// 上交所lev2指数消息
struct EMQSseIdx
{
    /// 初始化结构体
    EMQSseIdx()
    {
        memset(this, 0, sizeof(EMQSseIdx));
    }

    /// 包头
    EMQSseHead                   m_head;
    /// 行情更新时间,格式如：HHMMSS（秒）HH=00-23, MM=00-59, SS=00-59(秒)
    unsigned int                      m_quote_update_time;
    /// 证券代码
    char                              m_symbol[SSE_SYMBOL_LEN];
    /// 0：指数  1：股票 2：基金 3：债券 4：回购 5：权证 6：期货 7：外汇 8：利率 9：期权 10：其他
    unsigned char                     m_security_type;
    /// 昨收价， 实际值需要除以 100000
    unsigned int                      m_pre_close_price;
    /// 开盘价， 实际值需要除以 100000
    unsigned int                      m_open_price;
    /// 成交额， 实际值需要除以 10
    unsigned long long                m_total_value;
    /// 最高价， 实际值需要除以 100000
    unsigned int                      m_day_high_price;
    /// 最低价， 实际值需要除以 100000
    unsigned int                      m_day_low_price;
    /// 最新价， 实际值需要除以 100000
    unsigned int                      m_last_price;
    /// 成交量， 实际值需要除以 100000
    unsigned long long                m_total_quantity;
    /// 今收盘价， 实际值需要除以 100000
    unsigned int                      m_today_close_price;
};

/// 上交所lev2建树档位单元
struct EMQSseL2TreePriceQuantityUnit
{
    /// 价格， 实际值需要除以 1000
    unsigned int                      m_price;
    /// 数量， 实际值需要除以 1000
    unsigned long long                m_quantity;
};

/// 上交所lev2 建树消息
struct EMQSseTree
{
    /// 初始化结构体
    EMQSseTree()
    {
        memset(this, 0, sizeof(EMQSseTree));
    }

    /// 包头
    EMQSseHead                        m_head;
    /// 通道号
    unsigned int                      m_channel_num;
    /// 行情时间
    unsigned int                      m_quote_update_time;
    /// 标的名称
    char                              m_symbol[SSE_SYMBOL_LEN];
    /// 股票/合约类型  0：指数    1：股票 2：基金 3：债券 4：回购 5：权证 6：期货 7：外汇 8：利率 9：期权 10：其他
    unsigned char                     m_security_type;
    /// 业务序列号
    unsigned long long                m_biz_index;
    /// 昨收价， 实际值需要除以 1000
    unsigned int                      m_pre_close_price;
    /// 开盘价， 实际值需要除以 1000
    unsigned int                      m_open_price;
    /// 最高价， 实际值需要除以 1000
    unsigned int                      m_day_high_price;
    /// 最低价， 实际值需要除以 1000
    unsigned int                      m_day_low_price;
    /// 最新价， 实际值需要除以 1000
    unsigned int                      m_last_price;
    /// 今收盘价， 实际值需要除以 1000
    unsigned int                      m_today_close_price;
    /// 0:其他    1:启动 2:开市集合竞价 3:连续自动撮合 4:停牌 5:收盘集合竞价
    /// 6:闭市，自动计算闭市价格  7:交易结束  8:产品未上市

    /// 当前品种交易状态
    unsigned char                     m_instrument_status;
    /// Bit7-Bit4(m_trading_status&0xF0): 0x00:表示启动（开市前) 0x10:表示开盘集合竞价 0x20:表示连续交易 0x30:表示闭市
    /// Bit7-Bit4(m_trading_status&0xF0): 0x40:表示合约停牌 0x50:表示可恢复交易的熔断时段（盘中集合竞价） 0x60:表示不可恢复交易的熔断时段（暂停交易至闭市）
    /// Bit7-Bit4(m_trading_status&0xF0): 0x70:表示收盘集合竞价时段 0x80:表示波动性中断（适用于股票期权) 0x15:表示无意义
    /// Bit3(m_trading_status&0x08): 0x08: 表示此合约可正常交易 0x00:表示此合约不可正常交易
    /// Bit2(m_trading_status&0x04): 0x04: 表示已上市 0x00:表示未上市
    /// Bit1(m_trading_status&0x02): 0x02: 表示此合约在当前时段接受订单申报 0x00:表示此合约在当前时段不接受订单申报
    /// Bit0:预留

    /// 当前产品状态
    unsigned char                     m_trading_status;

    /// 6个字节的保留字段
    unsigned char                     m_reserved_0[6];
    /// 总成交笔数
    unsigned int                      m_total_trade_num;
    /// 总成交量， 实际值需要除以 1000
    unsigned long long                m_total_quantity;
    /// 总成交金额， 实际值需要除以 100000
    unsigned long long                m_total_value;
    /// 委托买入数量， 实际值需要除以 1000
    unsigned long long                m_total_bid_quantity;
    /// 加权平均委托买入价格， 实际值需要除以 1000
    unsigned int                      m_total_bid_weighted_avg_price;
    /// 委托卖出总量， 实际值需要除以 1000
    unsigned long long                m_total_ask_quantity;
    /// 加权平均委托卖价格， 实际值需要除以 1000
    int                               m_total_ask_weighted_avg_price;
    /// 债券到期收益率
    int                               m_yield_to_maturity;
    /// 申买档位数
    unsigned char                     m_bid_depth;
    /// 申卖档位数
    unsigned char                     m_ask_depth;
    /// 2字节的保留字段
    unsigned char                     m_reserved_1[2];
    /// 申买档位信息
    EMQSseL2TreePriceQuantityUnit m_bid_unit[SSE_LEV2_DEPTH];
    /// 申卖档位信息
    EMQSseL2TreePriceQuantityUnit m_ask_unit[SSE_LEV2_DEPTH];
};

/// 上交所lev2债券快照档位单元
struct EMQSseL2BondPriceQuantityUnit
{
    /// 价格， 实际值需要除以 1000
    unsigned int                      m_price;
    /// 数量， 实际值需要除以 1000
    unsigned long long                m_quantity;
};
// 上交所lev2债券快照
struct EMQSseBondSnap
{
    EMQSseBondSnap()
    {
        memset(this, 0, sizeof(EMQSseBondSnap));                  // 初始化结构体
    }

    /// 包头
    EMQSseHead                   m_head;
    /// 行情更新时间,格式如：HHMMSSsss（千分之一秒）HH=00-23, MM=00-59, SS=00-59(秒) sss=000-999(千分之一秒) 如 143025002 表示 14:30:25.002
    unsigned int                      m_quote_update_time;
    /// 保留字段
    unsigned char                     m_reserved_0[4];
    /// 合约
    char                              m_symbol[SSE_SYMBOL_LEN];
    ///     证券类型            证券子类型
    ///     0            指数   0              指数
    ///                         255            未分类
    ///     1            股票   0              主板
    ///                         1
    ///                         2              创业板
    ///                         3              B股
    ///                         4              H股
    ///                         5              科创板
    ///                         255            未分类
    ///     2            基金   248            LOF基金
    ///                         249            ETF基金
    ///                         255            未分类
    ///     3            债券   248            国债
    ///                         249            可转债
    ///                         255            未分类
    ///     4            回购   248            国债回购
    ///                         255            未分类
    ///     9            期权   248            股票期权
    ///                         249            ETF期权
    ///                         255            未分类
    ///     10           其他

    /// 证券类型
    unsigned char                     m_security_type;
    /// 证券子类型
    unsigned char                     m_sub_security_type;
    /// 保留字段
    unsigned char                     m_reserved_1[3];
    /// 昨收盘价， 实际值需要除以 1000
    unsigned int                      m_pre_close_price;
    /// 开盘价， 实际值需要除以 1000
    unsigned int                      m_open_price;
    /// 最高价， 实际值需要除以 1000
    unsigned int                      m_day_high_price;
    /// 最低价 ， 实际值需要除以 1000
    unsigned int                      m_day_low_price;
    /// 最新价， 实际值需要除以 1000
    unsigned int                      m_last_price;
    /// 收盘价， 实际值需要除以 1000
    unsigned int                      m_today_close_price;
    /// 0:其他    1:启动 2:开市集合竞价 3:连续自动撮合 4:停牌
    /// 6:闭市，自动计算闭市价格  7:交易结束  8:产品未上市

    /// 当前品种交易状态
    unsigned char                     m_instrument_status;
    /// 保留字段
    unsigned char                     m_reserved_2[3];
    /// 总成交笔数
    unsigned int                      m_total_trade_num;
    /// 总成交量， 实际值需要除以 1000
    unsigned long long                m_total_quantity;
    /// 总成交金额， 实际值需要除以 100000
    unsigned long long                m_total_value;
    /// 委托买入数量， 实际值需要除以 1000
    unsigned long long                m_total_bid_quantity;
    /// 加权平均委托买入价格， 实际值需要除以 1000
    unsigned int                      m_total_bid_weighted_avg_price;
    /// 委托卖出总量， 实际值需要除以 1000
    unsigned long long                m_total_ask_quantity;
    /// 加权平均委托卖价格， 实际值需要除以 1000
    unsigned int                      m_total_ask_weighted_avg_price;
    /// 买入撤单笔数
    unsigned int                      m_withdraw_bid_num;
    /// 买入撤单数量 实际值需要除以 1000
    unsigned long long                m_withdraw_bid_amount;
    /// 买入撤单金额 实际值需要除以 100000
    unsigned long long                m_withdraw_bid_price;
    /// 卖出撤单笔数
    unsigned int                      m_withdraw_ask_num;
    /// 卖出撤单数量 实际值需要除以 1000
    unsigned long long                m_withdraw_ask_amount;
    /// 卖出撤单金额 实际值需要除以 100000
    unsigned long long                m_withdraw_ask_price;
    /// 买入总笔数
    unsigned int                      m_total_bid_num;
    /// 卖出总笔数
    unsigned int                      m_total_ask_num;
    /// 买入委托成交最大等待时间
    unsigned int                      m_bid_trade_max_duration;
    /// 卖出委托成交最大等待时间
    unsigned int                      m_ask_trade_max_duration;
    /// 申买档位数
    unsigned char                     m_bid_depth;
    /// 申卖档位数
    unsigned char                     m_ask_depth;
    /// 保留字段
    unsigned char                     m_reserved_3[6];
    /// 申买信息
    EMQSseL2BondPriceQuantityUnit   m_bid_unit[SSE_LEV2_DEPTH];
    /// 申卖信息
    EMQSseL2BondPriceQuantityUnit   m_ask_unit[SSE_LEV2_DEPTH];
};

/// 债券逐笔
struct EMQSseBondTick
{
    /// 初始化结构体
    EMQSseBondTick()
    {
        memset(this, 0, sizeof(EMQSseBondTick));
    }

    /// 包头
    EMQSseHead                   m_head;
    /// 序号从1开始,按通道连续
    unsigned int                      m_tick_index;
    /// 通道号
    unsigned int                      m_channel_num;
    /// 标的名称
    char                              m_symbol[SSE_SYMBOL_LEN];
    ///     证券类型            证券子类型
    ///     0            指数   0              指数
    ///                         255            未分类
    ///     1            股票   0              主板
    ///                         1
    ///                         2              创业板
    ///                         3              B股
    ///                         4              H股
    ///                         5              科创板
    ///                         255            未分类
    ///     2            基金   248            LOF基金
    ///                         249            ETF基金
    ///                         255            未分类
    ///     3            债券   248            国债
    ///                         249            可转债
    ///                         255            未分类
    ///     4            回购   248            国债回购
    ///                         255            未分类
    ///     9            期权   248            股票期权
    ///                         249            ETF期权
    ///                         255            未分类
    ///     10           其他

    /// 证券类型
    unsigned char                     m_security_type;
    /// 证券子类型
    unsigned char                     m_sub_security_type;
    /// 订单或成交时间,格式如：HHMMSSsss（千分之一秒）HH=00-23, MM=00-59, SS=00-59(秒) sss=000-999(千分之一秒) 如 143025002 表示 14:30:25.002
    unsigned int                      m_tick_time;
    /// 类型， A新增订单， D删除订单， 删除订单， S产品状态订单， T成交
    unsigned char                     m_tick_type;
    /// 买方订单号
    unsigned long long                m_buy_num;
    /// 卖方订单号
    unsigned long long                m_sell_num;
    /// 价格，对产品状态订单无意义       实际值需要除以 1000
    unsigned int                      m_price;
    /// 数量（手），对产品状态订单无意义 实际值需要除以 1000
    unsigned long long                m_quantity;
    /// 成交额，仅适用于成交消息         实际值需要除以 100000
    unsigned long long                m_trade_value;
    /// 买卖标志，若为订单： B - 买单， S - 卖单；若为成交： B - 外盘， 主动买， S - 内盘， 主动卖 N - 未知 。
    char                              m_side_flag;
    /// 当前品种交易状态，仅适用于产品状态订单
    unsigned char                     m_instrument_status;
    /// 保留字段
    unsigned char                     m_reserved[8];
};

/// 逐笔合并
struct EMQSseTick
{
    /// 初始化结构体
    EMQSseTick()
    {
        memset(this, 0, sizeof(EMQSseTick));
    }

    /// 行情序号
    unsigned int                      m_sequence;
    /// 保留字段
    unsigned int                      m_reserved_1;
    /// 行情类型
    unsigned char                     m_message_type;
    /// 序号从1开始,按通道连续
    unsigned long long                m_tick_index;
    /// 通道号
    unsigned short                    m_channel_num;
    /// 保留字段
    unsigned short                    m_reserved_2;
    /// 标的名称
    char                              m_symbol[SSE_SYMBOL_LEN];
    /// 订单或成交时间,格式如：HHMMSSss（百分之一秒）HH=00-23, MM=00-59, SS=00-59(秒) ss=00-99(百分之一秒) 如 14302502 表示 14:30:25.02
    unsigned int                      m_tick_time;
    /// 类型， A新增订单， D删除订单， S产品状态订单， T成交
    unsigned char                     m_tick_type;
    /// 买方订单号
    unsigned long long                m_buy_num;
    /// 卖方订单号
    unsigned long long                m_sell_num;
    /// 价格，对产品状态订单无意义       实际值需要除以 1000
    unsigned int                      m_price;
    /// 数量（手），对产品状态订单无意义 实际值需要除以 1000
    unsigned long long                m_quantity;
    /// 对于新增委托，表示已成交的委托数量， 字段类型为 uInt64_1000, 实际值需要除以 1000；
    /// 对于成交，表示成交金额 （ 元 ）， 字段类型为 uInt64_100000, 实际值需要除以 100000；
    /// 其他无意义

    /// 成交额
    unsigned long long                m_trade_value;

    /// | TickType 类型 | m_tick_type 取值 |     SideFlag 含义      | m_side_flag 取值 |
    /// | ------------- | ---------------- | ---------------------- | ---------------- |
    /// |   新增订单    |       'A'        |          买单          |       0x00       |
    /// |               |                  |          卖单          |       0x01       |
    /// | ------------- | ---------------- | ---------------------- | ---------------- |
    /// |   删除订单    |       'D'        |          买单          |       0x00       |
    /// |               |                  |          卖单          |       0x01       |
    /// | ------------- | ---------------- | ---------------------- | ---------------- |
    /// | 产品状态订单  |       'S'        |          其他          |       0x00       |
    /// |               |                  |          启动          |       0x01       |
    /// |               |                  |      开市集合竞价      |       0x02       |
    /// |               |                  |      连续自动撮合      |       0x03       |
    /// |               |                  |          停牌          |       0x04       |
    /// |               |                  |      收盘集合竞价      |       0x05       |
    /// |               |                  | 闭市, 自动计算闭市价格 |       0x06       |
    /// |               |                  |        交易结束        |       0x07       |
    /// |               |                  |       产品未上市       |       0x08       |
    /// | ------------- | ---------------- | ---------------------- | ---------------- |
    /// |     成交      |       'T'        |      外盘 主动买       |       0x00       |
    /// |               |                  |      内盘 主动卖       |       0x01       |
    /// |               |                  |          未知          |       0x02       |

    /// 买卖方向，根据TickType不同含义不同，参考附表证券交 易状态表
    unsigned char                     m_side_flag;
};

#pragma pack(pop)
