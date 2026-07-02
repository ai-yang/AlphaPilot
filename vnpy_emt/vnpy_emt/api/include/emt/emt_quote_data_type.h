/////////////////////////////////////////////////////////////////////////
///@author 东方财富证券股份有限公司
///@file EMQ_quote_data_type.h
///@brief 定义兼容数据基本类型
/////////////////////////////////////////////////////////////////////////
#ifndef _EMQ_QUOTE_DATA_TYPE_H_
#define _EMQ_QUOTE_DATA_TYPE_H_
#include <cinttypes>

#pragma pack(1)
/// API版本号
#define API_VERSION	"2.19.0"
///内部协议通信版本
#define EMT_VERSION 1

/// 存放证券代码的字符串长度
#define EMQ_TICKER_LEN 16
/// 存放证券名称的字符串长度
#define EMQ_TICKER_NAME_LEN 64

#define EMQ_HK_TICKER_LEN 8
#define EMQ_BJGZ_TICKER_LEN 8

/////////////////////////////////////////////////////////////////////////
///@brief EMQ_LOG_LEVEL是日志输出级别类型
/////////////////////////////////////////////////////////////////////////
typedef enum EMQ_LOG_LEVEL {
	EMQ_LOG_LEVEL_TRACE,
	EMQ_LOG_LEVEL_DEBUG,
	EMQ_LOG_LEVEL_INFO,
	EMQ_LOG_LEVEL_WARNING,
	EMQ_LOG_LEVEL_ERROR,
	EMQ_LOG_LEVEL_FATAL
}EMQ_LOG_LEVEL;

/////////////////////////////////////////////////////////////////////////
///@brief EMQ_PROTOCOL_TYPE是通讯传输协议方式
/////////////////////////////////////////////////////////////////////////
typedef enum EMQ_PROTOCOL_TYPE
{
	EMQ_PROTOCOL_TCP = 1,	///<采用TCP方式传输
	EMQ_PROTOCOL_UDP		///<采用UDP方式传输(仅行情接口支持)
}EMQ_PROTOCOL_TYPE;

/////////////////////////////////////////////////////////////////////////
///@brief EMQ_EXCHANGE_TYPE是交易所类型，行情里使用
/////////////////////////////////////////////////////////////////////////
typedef enum EMQ_EXCHANGE_TYPE
{
	EMQ_EXCHANGE_SH = 1,	    ///<上证
	EMQ_EXCHANGE_SZ,		    ///<深证
	EMQ_EXCHANGE_SHHK,			///<上证港股通
	EMQ_EXCHANGE_SZHK,		    ///<深证港股通
	EMQ_EXCHANGE_BJGZ,		    ///<北交所股转行情
	EMQ_EXCHANGE_UNKNOWN = 100  ///<不存在的交易所类型
}EMQ_EXCHANGE_TYPE;


//////////////////////////////////////////////////////////////////////////
///@brief EMQ_TICKER_TYPE证券类型
//////////////////////////////////////////////////////////////////////////
typedef enum EMQ_TICKER_TYPE
{
	EMQ_TICKER_TYPE_STOCK = 0,            ///<普通股票
	EMQ_TICKER_TYPE_INDEX,                ///<指数
	EMQ_TICKER_TYPE_FUND,                 ///<基金
	EMQ_TICKER_TYPE_BOND,                 ///<债券
	EMQ_TICKER_TYPE_OPTION,               ///<期权
	EMQ_TICKER_TYPE_TECH_STOCK,           ///<科创板股票（上海）
	EMQ_TICKER_TYPE_REPURCHASE,           ///<质押式回购
	EMQ_TICKER_TYPE_WARRANT,              ///<权证
	EMQ_TICKER_TYPE_HKSTOCK,			  ///<港股通
	EMQ_TICKER_TYPE_BJGZ,				  ///<北交所股转
	EMQ_TICKER_TYPE_UNKNOWN = 100         ///<未知类型

}EMQ_TICKER_TYPE;

/////////////////////////////////////////////////////////////////////////
///@brief EMQ_QUALIFICATION_TYPE是一个证券适当性枚举类型
/////////////////////////////////////////////////////////////////////////
typedef enum EMQ_QUALIFICATION_TYPE
{
	EMQ_QUALIFICATION_PUBLIC = 0,			///<公众投资者，合格投资者与机构投资者均可
	EMQ_QUALIFICATION_COMMON = 1,			///<仅合格投资者与公众投资者
	EMQ_QUALIFICATION_ORGANIZATION = 2,		///<仅限机构投资者
	EMQ_QUALIFICATION_UNKNOWN = 3			///<未知，期权等可能为此种类型
}EMQ_QUALIFICATION_TYPE;


/////////////////////////////////////////////////////////////////////////
///@brief EMQ_SECURITY_TYPE是一个证券详细分类枚举类型
/////////////////////////////////////////////////////////////////////////
typedef enum EMQ_SECURITY_TYPE {
	/// 主板股票
	EMQ_SECURITY_MAIN_BOARD = 0,
	/// 中小板股票
	EMQ_SECURITY_SECOND_BOARD,
	/// 创业板股票
	EMQ_SECURITY_STARTUP_BOARD,
	/// 指数
	EMQ_SECURITY_INDEX,
	/// 科创板股票(上海)
	EMQ_SECURITY_TECH_BOARD = 4,
	/// 国债
	EMQ_SECURITY_STATE_BOND = 5,
	/// 企业债
	EMQ_SECURITY_ENTERPRICE_BOND = 6,
	/// 公司债
	EMQ_SECURITY_COMPANEY_BOND = 7,
	/// 转换债券
	EMQ_SECURITY_CONVERTABLE_BOND = 8,
	/// 国债逆回购
	EMQ_SECURITY_NATIONAL_BOND_REVERSE_REPO = 12,
	/// 本市场股票 ETF
	EMQ_SECURITY_ETF_SINGLE_MARKET_STOCK = 14,
	/// 跨市场股票 ETF
	EMQ_SECURITY_ETF_INTER_MARKET_STOCK,
	/// 本市场实物债券 ETF
	EMQ_SECURITY_ETF_SINGLE_MARKET_BOND = 17,
	/// 黄金 ETF
	EMQ_SECURITY_ETF_GOLD = 19,
	/// 分级基金子基金
	EMQ_SECURITY_STRUCTURED_FUND_CHILD = 24,
	/// 深交所仅申赎基金
	EMQ_SECURITY_SZSE_RECREATION_FUND = 26,
	/// 个股期权
	EMQ_SECURITY_STOCK_OPTION = 29,
	/// ETF期权
	EMQ_SECURITY_ETF_OPTION = 30,
	/// 配股
	EMQ_SECURITY_ALLOTMENT = 100,

	/// 上交所申赎型货币基金
	EMQ_SECURITY_MONETARY_FUND_SHCR = 110,
	/// 上交所交易型货币基金
	EMQ_SECURITY_MONETARY_FUND_SHTR = 111,
	/// 深交所货币基金
	EMQ_SECURITY_MONETARY_FUND_SZ = 112,

	/// 其他
	EMQ_SECURITY_OTHERS = 255
}EMQ_SECURITY_TYPE;

/////////////////////////////////////////////////////////////////////////
///@brief RebuildDataType 重建数据类型
/////////////////////////////////////////////////////////////////////////
typedef enum EMQ_REBUILD_DATA_TYPE {
	SZE_ORDER_DATA = 11,								///< 深市委托
	SZE_EXE_DATA = 12,									///< 深市成交
	SZE_BOND_ORDER_DATA = 13,							///< 深市债券委托
	SZE_BOND_EXE_DATA = 14,								///< 深市债券成交
	SSE_ORDER_DATA = 15,								///< 沪市委托
	SSE_EXE_DATA = 16,									///< 沪市成交
	SZE_BOND_TBT_DATA = 17								///< 沪市债券逐笔
}EMQ_REBUILD_DATA_TYPE;


#pragma pack()

#endif
