/*****************************************************************************
*  @file     quote_bse_define.h                                          *
*  @brief    北京证券交易所NQHQ.DBF行情数据体定义                              *
*  Details.                                                                  *
*                                                                            *
*****************************************************************************/
#pragma once
#include <inttypes.h>

#pragma pack(8)
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// NQHQ.DBF广播行情数据体定义
typedef struct
{
	char DBFTIME[6];		// DBF文件当前时间,格式:HHMMSS
	char DBFSTATUS[4];		// DBF文件当前状态:0000 - 非收市行情(正式);0001 - 收市行情(正式);0002 - 盘后行情(正式);0010 - 非收市行情(测试);0011 - 收市行情(测试);0012 - 盘后行情(测试);
	char HQZQDM[6];			// 证券代码
	char  HQZQJC[8];		// 证券简称
	double HQZRSP;			// 昨日收盘价
	double  HQJRKP;			// 今日开盘价
	double  HQZJCJ;			// 最近成交价
	uint64_t HQCJSL;		// 成交数量
	double HQCJJE;			// 成交金额
	uint64_t HQCJBS;		// 成交笔数
	double HQZGCJ;			// 最高成交价
	double HQZDCJ;			// 最低成交价
	double HQSYL1;			// 市盈率1
	double HQSYL2;			// 市盈率2
	double HQJSD1;			// 价格升跌1
	double HQJSD2;			// 价格升跌2
	uint64_t  HQHYCC;		// 合约持仓量
	double HQSJW5;			// 卖价位五
	uint64_t HQSSL5;		// 卖数量五
	double HQSJW4;			// 卖价位四
	uint64_t HQSSL4;		// 卖数量四
	double HQSJW3;			// 卖价位三
	uint64_t HQSSL3;		// 卖数量三
	double HQSJW2;			// 卖价位二
	uint64_t HQSSL2;		// 卖数量二
	double HQSJW1;			// 卖价位一/叫卖揭示价
	uint64_t HQSSL1;		// 卖数量一
	double  HQBJW1;			// 买价位一/叫买揭示价
	uint64_t HQBSL1;		// 买数量一
	double  HQBJW2;			// 买价位二
	uint64_t HQBSL2;		// 买数量二
	double  HQBJW3;			// 买价位三
	uint64_t HQBSL3;		// 买数量三
	double  HQBJW4;			// 买价位四
	uint64_t HQBSL4;		// 买数量四
	double  HQBJW5;			// 买价位五
	uint64_t HQBSL5;		// 买数量五
}EMQBseSnap;

#pragma pack()
