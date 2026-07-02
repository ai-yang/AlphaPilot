/*!
* @file   	sze_hpf_define.h
* @brief	盛立深市行情输出结构体
**/
#pragma once
#include <cstring>

#define		SZE_EXCHANGE_ID				(101)

#define		SZE_REPLACE_MSG_TYPE		(21)
#define		SZE_IDX_MSG_TYPE			(22)
#define		SZE_ORDER_MSG_TYPE			(23)
#define		SZE_EXECUTION_MSG_TYPE		(24)
#define		SZE_AFTER_MSG_TYPE			(25)					/// 盘后定价快照	sze_2_3_2
#define		SZE_TREE_MSG_TYPE			(29)
#define		SZE_IBR_TREE_MSG_TYPE       (28)                    // 深交所IBR建树快照
#define		SZE_TURNOVER_MSG_TYPE       (26)                    // 深交所成交量统计快照
#define		SZE_BOND_SNAP_MSG_TYPE      (80)                    // 深交所债券快照消息类型
#define		SZE_BOND_ORDER_MSG_TYPE     (81)                    // 深交所债券逐笔委托消息类型
#define		SZE_BOND_EXE_MSG_TYPE       (82)                    // 深交所债券逐笔成交消息类型


#define		SZE_LEV2_DEPTH              (10)                    // 深交所快照深度
#define		IBR_DEPTH					(5)

#define		SZE_HB_LEV2_SNAPSHOT_MSG_TYPE	(121)
#define		SZE_HB_IDX_MSG_TYPE				(122)
#define		SZE_HB_ORDER_MSG_TYPE			(123)
#define		SZE_HB_AFTER_MSG_TYPE			(125)
#define		SZE_HB_TURNOVER_MSG_TYPE		(126)
#define		SZE_HB_IBR_MSG_TYPE				(128)
#define		SZE_HB_LEV2_TREE_MSG_TYPE		(129)
#define		SZE_HB_BOND_SNAP_MSG_TYPE   	(180)				// 深交所债券快照心跳消息类型,api内部消化
#define		SZE_HB_BOND_TICK_MSG_TYPE   	(181)				// 深交所债券逐笔心跳消息类型,api内部消化


#pragma pack(push, 1)
struct sze_hpf_heartbeat_pkt
{
	sze_hpf_heartbeat_pkt()
	{
		memset(this, 0, sizeof(*this));
	}

	unsigned int						m_sequence;
	unsigned short						m_tick1;
	unsigned short						m_tick2;
	unsigned char						m_msg_type;
	unsigned char						m_reserved[7];
};

struct px_qty_unit
{
	unsigned int						m_price;
	long long							m_qty;
};

struct sze_hpf_pkt_head
{
	int									m_sequence;
	short								m_tick1;
	short								m_tick2;
	unsigned char						m_msg_type;
	unsigned char						m_security_type;
	unsigned char						m_sub_security_type;
	char								m_symbol[9];
	unsigned char						m_exchange_id;
	long long							m_quote_update_time;
	unsigned short						m_channel_no;
	long long							m_sequence_num;
	unsigned int 						m_md_stream_id;
};

struct sze_hpf_lev2_pkt
{
	sze_hpf_pkt_head					m_header;
	unsigned char 						m_trade_phase_code;
	long long							m_trade_num;
	long long							m_total_qty;
	long long							m_total_value;
	unsigned int						m_pre_close_price;
	unsigned int						m_last_price;
	unsigned int						m_open_price;
	unsigned int						m_day_high;
	unsigned int						m_day_low;
	unsigned int						m_today_close_price;
	unsigned int						m_total_bid_wvp;
	long long							m_total_bid_qty;
	unsigned int						m_total_ask_wvp;
	long long							m_total_ask_qty;
	unsigned int 						m_lpv;
	unsigned int 						m_iopv;
	unsigned int						m_upper_limit_price;
	unsigned int						m_low_limit_price;
	unsigned int 						m_open_interest;
	px_qty_unit							m_bid_unit[10];
	px_qty_unit							m_ask_unit[10];
};

struct sze_hpf_idx_pkt
{
	sze_hpf_pkt_head					m_header;
	long long							m_trade_num;
	long long							m_total_qty;
	long long							m_total_value;
	unsigned int						m_last_price;
	unsigned int						m_pre_close_price;
	unsigned int						m_open_price;
	unsigned int						m_day_high;
	unsigned int						m_day_low;
	unsigned int 						m_close_price;
	char								m_resv[5];
};

struct sze_hpf_order_pkt
{
	sze_hpf_pkt_head					m_header;
	unsigned int						m_px;
	long long							m_qty;
	char								m_side;
	char								m_order_type;
	char								m_resv[15];
};

struct sze_hpf_exe_pkt
{
	sze_hpf_pkt_head					m_header;
	long long							m_bid_app_seq_num;
	long long							m_ask_app_seq_num;
	unsigned int						m_exe_px;
	long long							m_exe_qty;
	char								m_exe_type;
};

struct sze_hpf_tree_pkt
{
	sze_hpf_pkt_head					m_header;
	long long							m_trade_num;
	unsigned long long					m_total_qty;
	long long							m_total_value;
	unsigned int						m_pre_close_price;
	unsigned int						m_last_price;
	unsigned int						m_open_price;
	unsigned int						m_day_high;
	unsigned int						m_day_low;
	unsigned int						m_today_close_price;
	unsigned int						m_total_bid_wvp;
	unsigned long long					m_total_bid_qty;
	unsigned int						m_total_ask_wvp;
	unsigned long long					m_total_ask_qty;
	unsigned int						m_upper_limit_price;
	unsigned int						m_low_limit_price;
	unsigned long long					m_market_open_total_bid;
	unsigned long long					m_market_open_total_ask;
	unsigned int						m_total_lev2_bid;
	unsigned int						m_total_lev2_ask;
	px_qty_unit							m_bid_unit[10];
	px_qty_unit							m_ask_unit[10];
	char								m_ch_gap_flag;
	char								m_resv[4];
};

//盘后定价，2.3.2
struct sze_hpf_after_pkt
{
	sze_hpf_pkt_head					m_header;
	unsigned char						m_trading_phase_code;
	long long							m_trade_num;
	unsigned long long int				m_total_qty;
	unsigned long long int				m_total_value;
	unsigned int						m_pre_close_price;
	unsigned int						m_exe_price;
	unsigned long long int				m_bid_qty;
	unsigned long long int				m_ask_qty;
	char								m_resv[4];
};

//成交量统计sze3.0
struct sze_hpf_turnover_pkt
{
	sze_hpf_pkt_head					m_header;
	unsigned char						m_trading_phase_code;
	long long							m_prev_close_px;
	long long							m_num_trade;
	unsigned long long					m_total_volumn_trade;
	unsigned long long					m_total_value_trade;
	unsigned int						m_stock_num;
};

// ibr_tree
struct sze_hpf_ibr_tree_pkt
{
	sze_hpf_pkt_head					m_header;
	unsigned int						m_total_bid_weighted_avgPx;
	unsigned long long					m_total_bid_qty;
	unsigned int						m_total_ask_weighted_avgPx;
	unsigned long long					m_total_ask_qty;
	unsigned int						m_total_level_bid;
	unsigned int						m_total_level_ask;
	px_qty_unit							m_bid_unit[IBR_DEPTH];
	px_qty_unit							m_ask_unit[IBR_DEPTH];
	char								m_reserved[5];
};



// 深交所全新快照消息
struct sze_hpf_bond_snap_pkt
{
	sze_hpf_pkt_head                      m_head;                            // 包头
	unsigned char                     m_trading_status;                  // 交易状态码
	//******************************************************************************************
	// Bit7-Bit4(m_trading_status&0xF0):
	// 0x00:表示启动（开市前)
	// 0x10:表示开盘集合竞价
	// 0x20:表示连续交易
	// 0x30:表示闭市
	// 0x40:表示合约停牌
	// 0x50:表示可恢复交易的熔断时段（盘中集合竞价）
	// 0x60:表示不可恢复交易的熔断时段（暂停交易至闭市）
	// 0x70:表示收盘集合竞价时段
	// 0x80:表示波动性中断（适用于股票期权)
	// 0x15:表示无意义
	// Bit3(m_trading_status&0x08):
	// 0x08:?表示此合约可正常交易 0x00:表示此合约不可正常交易
	// Bit2(m_trading_status&0x04):
	// 0x04:表示已上市 0x00:表示未上市
	// Bit1(m_trading_status&0x02):
	// 0x02:表示此合约在当前时段接受订单申报 0x00:表示此合约在当前时段不接受订单申报
	// Bit0:预留
	//******************************************************************************************
	unsigned long long                m_total_trade_num;                 // 成交笔数
	unsigned long long                m_total_quantity;                  // 总成交量，          实际值需要除以 100
	unsigned long long                m_total_value;                     // 总成交额，          实际值需要除以 1000000
	unsigned int                      m_pre_close_price;                 // 昨收价，            实际值需要除以 10000
	unsigned int                      m_last_price;                      // 最新价，            实际值需要除以 10000
	unsigned int                      m_open_price;                      // 开盘价，            实际值需要除以 10000
	unsigned int                      m_day_high_price;                  // 最高价，            实际值需要除以 10000
	unsigned int                      m_day_low_price;                   // 最低价，            实际值需要除以 10000
	unsigned int                      m_today_close_price;               // 收盘价，            实际值需要除以 10000
	unsigned int                      m_total_trade_weighted_avg_price;  // 加权平均价，        实际值需要除以 10000
	unsigned int                      m_fluctuation_1;                   // 升跌 1,             实际值需要除以 10000
	unsigned int                      m_fluctuation_2;                   // 升跌 2,             实际值需要除以 10000
	unsigned int                      m_total_bid_weighted_avg_price;    // 买方挂单均价，      实际值需要除以 10000
	unsigned long long                m_total_bid_quantity;              // 买总量，            实际值需要除以 100
	unsigned int                      m_total_ask_weighted_avg_price;    // 卖方挂单均价，      实际值需要除以 10000
	unsigned long long                m_total_ask_quantity;              // 卖总量，            实际值需要除以 100

	unsigned int                      m_weighted_avg_price_BP;           // 加权平均涨跌 BP     实际值需要除以 10000
	unsigned int                      m_weighted_avg_pre_close_price;    // 昨收盘加权平均价    实际值需要除以 10000
	unsigned int                      m_auction_trade_last_price;        // 匹配成交最新价      实际值需要除以 10000
	unsigned char                     m_reserved[4];                     // 保留字段
	unsigned long long                m_auction_volume_trade;            // 匹配成交成交量      实际值需要除以 100
	unsigned long long                m_auction_value_trade;             // 匹配成交成交金额    实际值需要除以 1000000

	px_qty_unit	                      m_bid_unit[SZE_LEV2_DEPTH];        // 买方十档
	px_qty_unit	                      m_ask_unit[SZE_LEV2_DEPTH];        // 卖方十档
};

// 深交所债券逐笔委托
struct sze_hpf_bond_order_pkt
{
	sze_hpf_pkt_head                  m_head;                            // 包头
	/// 对逐笔委托价格转换说明如下：
	//  ****************************************************************************************************************
	//  |订单类型 \ 买卖方向 |                    买（1）            |                           卖（2）                    |
	//  |     市价（1）      |                    直接透传           |                           直接透传                   |
	//  |    本方最优(U）    |                    直接透传           |                           直接透传                   |
	//  |     限价（2）      |   如果小于 3 的取为 3，否则取原值     |   如果大于 999999997，取为 999999997，否则取原值     |
	//  *****************************************************************************************************************
	unsigned int                      m_price;                           // 价格，  实际值需要除以 10000
	unsigned long long                m_quantity;                        // 数量，  实际值需要除以 100
	char                              m_side;                            // 方向，‘1’=买 ‘2’=卖
	char                              m_order_type;                      // 订单类型
	//******************************************************************************************
	// '1'=市价  '2'=限价  'U'=本方最优
	//******************************************************************************************
	char                              m_reserved[15];                     // 保留字段
};

// 深交所债券逐笔成交
struct sze_hpf_bond_exe_pkt
{
	sze_hpf_pkt_head                  m_head;                           // 包头
	long long                         m_buy_num;                        // 买方包序号
	long long                         m_sell_num;                       // 卖方包序号
	unsigned int                      m_price;                          // 价格，   实际值需要除以 10000
	long long                         m_quantity;                       // 数量，   实际值需要除以 100
	char                              m_type;                           // 成交类型
	//******************************************************************************************
	// '4'=撤销  'F'=成交
	//******************************************************************************************
};

#pragma pack(pop)
