/*!****************************************************************************
	@file   	sse_hpf_define.h

	@brief		盛立行情输出结构体
******************************************************************************/
#pragma once
#include <cstring>

#define		SSE_EXCHANGE_ID				(100)

#define        SSE_SYMBOL_LEN                   (9)                     // 上交所合约长度
#define        SSE_LEV2_DEPTH                   (10)                    // 上交所lev2档位深度
#define        SSE_OPTION_DEPTH                 (5)                     // 上交所期权档位深度

#define        SSE_SECURITY_NAME_LEN            (9)
#define        SSE_PRODUCT_STATUS_LEN           (21)
#define        DATE_LEN                         (9)

#define		SSE_ORDER_MSG_TYPE			(32)
#define		SSE_INDEX_MSG_TYPE			(33)
#define		SSE_EXECUTION_MSG_TYPE		(34)
#define		SSE_OPTION_MSG_TYPE			(35)
#define		SSE_TREE_MSG_TYPE			(38)
#define		SSE_LEV2_MSG_TYPE			(39)
#define		SSE_BOND_SNAP_MSG_TYPE		(60)
#define		SSE_BOND_TICK_MSG_TYPE		(61)
#define		SSE_LEV2_STATIC_INFO_MSG_TYPE    (255)                   // 上交所lev2静态信息类型


#define		SSE_HB_TICK_MSG_TYPE		(132)
#define		SSE_HB_INDEX_MSG_TYPE		(133)
#define		SSE_HB_OPTION_MSG_TYPE		(135)
#define		SSE_HB_TREE_MSG_TYPE		(138)
#define		SSE_HB_FULL_MSG_TYPE		(139)
#define		SSE_HB_BOND_MSG_TYPE		(160)		// 债券lev2快照心跳
#define		SSE_HB_BOND_TICK_MSG_TYPE	(161)		// 债券逐笔心跳

#pragma pack(push, 1)
struct sse_hpf_heartbt_pkt
{
	sse_hpf_heartbt_pkt()
	{
		memset(this, 0, sizeof(sse_hpf_heartbt_pkt));
	}

	unsigned int						m_sequence;						// 取当前输出通道内最新消息的SeqNum
	unsigned char						m_reserved_0[4];				// 4个字节的保留字段
	unsigned char						m_message_type;					// 等于各通道msgtype+100
	unsigned char						m_reserved_1[7];				// 保留字段
};

struct sse_hpf_head
{
	unsigned int						m_sequence;
	unsigned short						m_tick1;
	unsigned short						m_tick2;
	unsigned char						m_message_type;
	unsigned short						m_message_len;		/// 包括此消息头的长度
	unsigned char						m_exchange_id;
	unsigned short						m_quote_date_year;
	unsigned char						m_quote_date_month;
	unsigned char						m_quote_date_day;
	unsigned int						m_send_time;
	unsigned char						m_category_id;
	unsigned int						m_msg_seq_id;
	unsigned char						m_seq_lost_flag;	/// 1=有丢包，0=没有丢包
};

struct px_level
{
	px_level()
	{
		memset(this, 0, sizeof(px_level));
	}
	char								m_lev_operator;
	char								m_resv[3];
	unsigned int						m_px;
	unsigned long long					m_qty;
};
//逐笔委托
struct sse_hpf_order_pkt
{
	sse_hpf_order_pkt()
	{
		memset(this, 0, sizeof(sse_hpf_order_pkt));
	}
	sse_hpf_head						m_head;

	unsigned int						m_order_index;
	unsigned int						m_channel;
	char								m_symbol[9];
	unsigned int						m_order_time;
	unsigned char						m_order_type;
	unsigned long long					m_order_no;
	unsigned int						m_order_price;
	unsigned long long					m_balance;
	unsigned char						m_reserved_0[15];
	unsigned char						m_order_bs_flag;
	unsigned long long					m_biz_index;
	unsigned char						m_reserved_1[4];
};
//指数
struct sse_hpf_index_pkt
{
	sse_hpf_index_pkt()
	{
		memset(this, 0, sizeof(sse_hpf_index_pkt));
	}
	sse_hpf_head						m_head;

	unsigned int						m_quote_update_time;
	char								m_symbol[9];
	unsigned char						m_security_type;			/// 0=指数， 10=其他
	unsigned int						m_previous_close_price;
	unsigned int 						m_open_price;
	unsigned long long					m_total_value;
	unsigned int						m_day_high;
	unsigned int						m_day_low;
	unsigned int						m_last_price;
	unsigned long long					m_total_quantity;
	unsigned int						m_today_close_price;
};
//逐笔成交
struct sse_hpf_exe_pkt
{
	sse_hpf_exe_pkt()
	{
		memset(this, 0, sizeof(sse_hpf_exe_pkt));
	}
	sse_hpf_head						m_head;

	unsigned int						m_trade_index;
	unsigned int						m_channel;
	char								m_symbol[9];
	unsigned int						m_trade_time;
	unsigned int						m_trade_price;
	unsigned long long					m_trade_qty;
	unsigned long long					m_trade_money;
	unsigned long long					m_trade_buy_no;
	unsigned long long					m_trade_sell_no;
	char								m_trade_bs_flag;
	unsigned long long					m_biz_index;
	unsigned int						m_reserved;
};
//期权
struct stock_option_px_level
{
	stock_option_px_level()
	{
		memset(this, 0, sizeof(stock_option_px_level));
	}
	unsigned int							m_px;
	unsigned long long						m_qty;
};
struct sse_hpf_stock_option
{
	sse_hpf_stock_option()
	{
		memset(this, 0, sizeof(sse_hpf_stock_option));
	}
	sse_hpf_head							m_head;

	unsigned int							m_quote_update_time;
	unsigned char							m_security_type;
	char									m_symbol[9];
	unsigned char							m_image_status;
	unsigned char							m_reserved1;
	unsigned int							m_previous_close_price;
	unsigned int							m_previous_settle_price;
	unsigned int 							m_open_price;
	unsigned int							m_day_high;
	unsigned int							m_day_low;
	unsigned int 							m_last_price;
	unsigned int 							m_today_close_price;
	unsigned int 							m_settle_price;
	unsigned int 							m_dynamic_price;
	unsigned char 							m_reserved2[3];
	unsigned char							m_trading_status;
	unsigned long long						m_open_interest;
	unsigned int							m_num_trades;
	unsigned long long						m_volume;
	unsigned long long						m_turnover;
	unsigned char							m_no_bid_level;
	unsigned char							m_no_offer_level;
	stock_option_px_level					m_bid_px[5];
	stock_option_px_level					m_ask_px[5];
};
//快照
struct sse_hpf_lev2_header
{
	sse_hpf_head						m_head;

	unsigned int						m_quote_update_time;
	char								m_symbol[9];
	unsigned char						m_security_type;
	unsigned char						m_data_type;
	unsigned char						m_reserved1;
	unsigned int						m_previous_close_price;
	unsigned int 						m_open_price;
	unsigned int						m_day_high;
	unsigned int						m_day_low;
	unsigned int						m_last_price;
	unsigned int						m_today_close_price;
	unsigned char						m_instrument_status;
	unsigned char						m_trading_status;
	unsigned short						m_reserved2;
	unsigned int						m_total_trade_number;
	unsigned long long					m_total_quantity;
	unsigned long long					m_total_value;

	unsigned long long					m_total_bid_qty;
	unsigned int						m_total_bid_weighted_avg_px;
	unsigned long long					m_total_ask_qty;
	unsigned int						m_total_ask_weighted_avg_px;
	unsigned int						m_IOPV;
	unsigned char						m_bid_depth;
	unsigned char						m_ask_depth;
};
struct sse_hpf_lev2
{
	sse_hpf_lev2()
	{
		memset(this, 0, sizeof(sse_hpf_lev2));
	}
	sse_hpf_lev2_header					m_lev2_header;
	px_level							m_bid_px[10];
	px_level							m_ask_px[10];
};
//建树
struct tree_px_level
{
	tree_px_level()
	{
		memset(this, 0, sizeof(tree_px_level));
	}
	unsigned int							m_px;
	unsigned long long						m_qty;
};
struct sse_hpf_tree_pkt
{
	sse_hpf_head						m_head;
	unsigned int						m_channel_id;
	unsigned int						m_quote_update_time;
	char								m_symbol[9];
	unsigned char						m_security_type;
	unsigned long long					m_biz_index;
	unsigned int						m_previous_close_price;
	unsigned int 						m_open_price;
	unsigned int						m_day_high;
	unsigned int						m_day_low;
	unsigned int						m_last_price;
	unsigned int						m_today_close_price;
	unsigned char						m_instrument_status;
	unsigned char						m_trading_status;
	unsigned char						m_reserved1[6];
	unsigned int						m_total_trade_number;
	unsigned long long					m_total_quantity;
	unsigned long long					m_total_value;
	unsigned long long					m_total_bid_qty;
	unsigned int						m_total_bid_weighted_avg_px;
	unsigned long long					m_total_ask_qty;
	unsigned int						m_total_ask_weighted_avg_px;
	unsigned int						m_yield_to_maturity;
	unsigned char						m_bid_depth;
	unsigned char						m_ask_depth;
	unsigned char						m_reserved2[2];
	tree_px_level						m_bid_px[10];
	tree_px_level						m_ask_px[10];
};

// 债券档位信息
struct sse_msg_bond_level_unit
{
	unsigned int					m_price;
	unsigned long long 				m_volumn;
};

// 债券建树快照
struct sse_msg_bond_snap_pkt
{
	sse_hpf_head					m_head;
	unsigned int					m_update_time;					// 行情时间
	char							m_reserved_0[4];				// 保留字段
	char							m_security_id[9];					// 债券代码
	char							m_secu_type;					// 证券类型
	char							m_sub_secu_type;				// 证券子类型
	char							m_reserved_1[3];				// 保留字段
	unsigned int					m_pre_close_px;					// 昨收价
	unsigned int					m_open_px;						// 开盘价
	unsigned int					m_day_high;						// 最高价
	unsigned int					m_day_low;						// 最低价
	unsigned int					m_last_px;						// 现价
	unsigned int					m_close_px;						// 今日收盘价
	char							m_instrument_status;			// 当前品种交易状态
	char							m_reserved_2[3];				// 保留字段
	unsigned int					m_trade_num;					// 成交笔数
	unsigned long long 				m_trade_volumn;					// 成交总量
	unsigned long long 				m_trade_value;					// 成交总金额
	unsigned long long 				m_total_qty_bid;				// 委托买入总量（手）
	unsigned int					m_weighted_avg_px_bid;			// 债券加权平均委买价格
	unsigned long long 				m_total_qty_ask;				// 委托卖出总量
	unsigned int					m_weighted_avg_px_ask;			// 债券加权平均委卖价格
	unsigned int					m_withdraw_buy_number;			// 买入撤单笔数
	unsigned long long 				m_withdraw_buy_amount;			// 买入撤单数量
	unsigned long long 				m_withdraw_buy_money;			// 买入撤单金额
	unsigned int					m_withdraw_sell_number;			// 卖出撤单笔数
	unsigned long long 				m_withdraw_sell_amount;			// 卖出撤单数量
	unsigned long long 				m_withdraw_sell_money;			// 卖出撤单金额
	unsigned int					m_total_bid_number;				// 买入总笔数
	unsigned int					m_total_offer_number;			// 卖出总笔数
	int								m_bid_trade_max_duration;		// 买入委托成交最大等待时间
	int								m_offer_trade_max_duration;		// 卖出委托成交最大等待时间
	char							m_bid_depth;					// 申买档位数
	char							m_ask_depth;					// 申卖档位数
	char							m_reserved_3[6];
	sse_msg_bond_level_unit			m_bid_levels[10];				// 申买信息
	sse_msg_bond_level_unit			m_offer_levels[10];				// 申卖信息
};

// 债券逐笔
struct sse_msg_bond_tick_pkt
{
	sse_hpf_head					m_head;
	unsigned int					m_tick_index;					// 序号，从1开始，按通道连续
	unsigned int					m_channel_id;					// 通道号
	char							m_security_id[9];					// 标的名称
	char							m_secu_type;					// 证券类型
	char							m_sub_secu_type;				// 证券子类型
	unsigned int					m_tick_time;					// 订单或成交时间
	char							m_tick_type;					// 类型， A新增订单， D删除订单， 删除订单， S产品状态订单， T成交
	unsigned long long 				m_buy_order_no;					// 买方订单号，对产品状态订单无意义
	unsigned long long 				m_sell_order_no;				// 卖方订单号，对产品状态订单无意义
	unsigned int					m_price;						// 价格，对产品状态订单无意义
	unsigned long long 				m_qty;							// 数量（手），对产品状态订单无意义
	unsigned long long 				m_trade_money;					// 成交金额（元），仅适用于成交消息
	char							m_side_flag;					// 买卖标志，若为订单： 买卖标志，若为订单： 买卖标志，若为订单： 买卖标志，若为订单： 买卖标志，若为订单： 买卖标志，若为订单： 买卖标志，若为订单： 买卖标志，若为订单： B - 买单， S - 卖单；若为成交： 卖单；若为成交： 卖单；若为成交： 卖单；若为成交： 卖单；若为成交： 卖单；若为成交： B - 外盘， 外盘， 主动买， S - 内盘， 主动卖N - 未知 。
	char							m_instrument_status;			// 股票 / 标的状态，仅适用于产品状态订单
	char							m_reserved[8];					// 保留字段
};

struct sse_static_msg_header
{
    unsigned int                    m_seq_num;                          // 发包的消息序号 从1开始
    unsigned char                   m_reserved[4];                      // 4个字节保留字段
    unsigned char                   m_msg_type;                         // 消息类型
    unsigned short                  m_msg_body_len;                     // 消息体长度
    bool                            m_batch_finish_flag;                // 当前静态文件发送完成标志
};

struct sse_static_msg_body
{
    unsigned char                   m_exchange_id;                             // 交易所id
    char                            m_symbol[SSE_SYMBOL_LEN];                  // 证券代码
    unsigned int                    m_send_time;                               // 行情发送时间，时分秒毫秒
    char                            m_static_file_date[DATE_LEN];              // 静态文件日期，YYYYMMDD, 以'\0'结束
    //涨跌幅限制类型：******************************************************************************************
    // ‘ ’ (十进制数字为32)表示无定义
    // ‘N’表示交易规则（2013修订版）3.4.13规定的有涨跌幅限制类型或者权证管理办法第22条规定
    // ‘R’表示交易规则（2013修订版）3.4.15和3.4.16规定的无涨跌幅限制类型
    // ‘S’表示回购涨跌幅控制类型
    // ‘F’表示基于参考价格的涨跌幅控制
    // ‘P’表示IPO上市首日的涨跌幅控制类型
    // ‘U’表示无任何价格涨跌幅控制类型
    //******************************************************************************************
    char                            m_price_limit_type;                        // 跌涨停限制类型
    double                          m_up_limit_price;                          // 涨停价
    double                          m_down_limit_price;                        // 跌停价
    unsigned long long int          m_bid_qty_unit;                            // 买数量单位
    unsigned long long int          m_ask_qty_unit;                            // 卖数量单位
    unsigned long long int          m_limit_upper_qty;                         // 限价申报数量上限
    unsigned long long int          m_limit_lower_qty;                         // 限价申报数量下限
    double                          m_price_changge_unit;                      // 申报最小变价单位
    unsigned long long int          m_market_upper_qty;                        // 市价申报数量上限
    unsigned long long int          m_market_lower_qty;                        // 市价申报数量下限
    char                            m_security_name[SSE_SECURITY_NAME_LEN];    // 证券名称，以'\0'结束
    // *******************************************************************************************
    //     证券类型            证券子类型
    //     0            指数   0              指数
    //                         255            未分类
    //     1            股票   0              主板
    //                         1
    //                         2              创业板
    //                         3              B股
    //                         4              H股
    //                         5              科创板
    //                         255            未分类
    //     2            基金   248            LOF基金
    //                         249            ETF基金
    //                         255            未分类
    //     3            债券   248            国债
    //                         249            可转债
    //                         255            未分类
    //     4            回购   248            国债回购
    //                         255            未分类
    //     9            期权   248            股票期权
    //                         249            ETF期权
    //                         255            未分类
    //     10           其他
    // *******************************************************************************************
    unsigned char                   m_ssecurity_type;                          // 证券类型
    unsigned char                   m_sub_ssecurity_type;                      // 证券子类型
    char                            m_finance_target_mark;                     // 融资标的标志 ‘ ’ (十进制数字为32)表示无定义,‘T’表示是融资标的证券,‘F’表示不是融资标的证券。
    char                            m_ssecurity_target_mark;                   // 融券标的标志 ‘ ’ (十进制数字为32)表示无定义,‘T’表示是融资标的证券,‘F’表示不是融资标的证券。
    char                            m_product_status[SSE_PRODUCT_STATUS_LEN];  // 产品状态, 以'\0'结束
    char                            m_listing_date[DATE_LEN];                  // 上市日期，格式为YYYYMMDD, 以'\0'结束
};

struct sse_static_msg
{
    sse_static_msg_header           m_header;
    sse_static_msg_body             m_body;
};

#pragma pack(pop)
