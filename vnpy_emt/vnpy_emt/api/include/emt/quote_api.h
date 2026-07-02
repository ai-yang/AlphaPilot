/////////////////////////////////////////////////////////////////////////
///@author 东方财富证券股份有限公司
///@file quote_api.h
///@brief 定义客户端行情接口
/////////////////////////////////////////////////////////////////////////

#pragma once
#include <string>

#include "emt_quote_data_type.h"
#include "sse_hpf_define.h"
#include "sze_hpf_define.h"
#include "emt_quote_struct.h"

#ifdef _WIN32
#ifdef LIB_QUOTE_API_EXPORT
#define QUOTE_API_ _declspec(dllexport)
#else
#define QUOTE_API_ _declspec(dllimport)
#endif
#else
#define QUOTE_API_
#endif // _WIN32

namespace EMQ {
namespace API {

class QuoteSpi {
  public:

    /**
     *   错误应答
     *   @attention                     此函数只有在服务器发生错误时才会调用，一般无需用户处理
     *   @param error_info              当服务器响应发生错误时的具体错误内容
     *   @return                        该函数返回为void
     */
    virtual void OnError(const EMTRspInfoStruct* error_info) {};

    /**
     *   指数行情通知
     *   @attention                     需要快速返回，否则阻塞后续消息，导致延时，当阻塞严重时，会触发断线
     *   @param index_data              指数行情数据，只有指数行情数据相关字段
     */
    virtual void OnIndexData(EMTIndexDataStruct* index_data) {};

    /**
     *   深度行情通知，包含买一卖一队列
     *   @attention                     需要快速返回，否则会堵塞后续消息，当堵塞严重时，会触发断线
     *   @param market_data             行情数据
     *   @param bid1_qty                买一队列数据
     *   @param bid1_count              买一队列的有效委托笔数
     *   @param max_bid1_count          买一队列总委托笔数
     *   @param ask1_qty                卖一队列数据
     *   @param ask1_count              卖一队列的有效委托笔数
     *   @param max_ask1_count          卖一队列总委托笔数
     */
    virtual void OnDepthMarketData(EMTMarketDataStruct* market_data, int64_t bid1_qty[], int32_t bid1_count, int32_t max_bid1_count, int64_t ask1_qty[], int32_t ask1_count, int32_t max_ask1_count) {};

    /**
     *   订阅全市场的指数行情应答
     *   @attention                     需要快速返回
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场
     *   @param error_info              订阅合约时发生错误时返回的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     */
    virtual void OnSubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info) {};

    /**
     *   退订全市场的指数行情应答
     *   @attention                     需要快速返回
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场
     *   @param error_info              取消订阅合约时发生错误时返回的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     */
    virtual void OnUnSubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info) {};

    /**
     *   订阅指数行情应答
     *   @attention                     每条订阅的合约对应一条订阅应答，需要快速返回，否则会阻塞后续消息，当阻塞严重时，会触发断线
     *   @param ticker                  订阅的合约编号代码
     *   @param error_info              订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次订阅的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnSubIndexData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     *   退订指数行情应答
     *   @attention                     每条订阅的合约对应一条退订应答，需要快速返回，否则会阻塞后续消息，当阻塞严重时，会触发断线
     *   @param ticker                  订阅的合约编号代码
     *   @param error_info              取消订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次取消订阅的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnUnSubIndexData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     *   订阅全市场股票快照行情应答
     *   @attention                     需要快速返回
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场
     *   @param error_info              订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     */
    virtual void OnSubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info) {};

    /**
     *   退订全市场的股票快照行情应答
     *   @attention                     需要快速返回
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场
     *   @param error_info              取消订阅合约时发生错误时返回的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     */
    virtual void OnUnSubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info) {};

    /**
     *   订阅快照行情应答，包括股票，基金，债券，权证和质押式回购
     *   @attention                     每条订阅的合约对应一条订阅应答，需要快速返回，否则会阻塞后续消息，当阻塞严重时，会触发断线
     *   @param ticker                  订阅的合约编号代码
     *   @param error_info              订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次订阅的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnSubMarketData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     *   退订快照行情应答，包括股票，基金，债券，权证和质押式回购
     *   @attention                     每条订阅的合约对应一条订阅应答，需要快速返回，否则会阻塞后续消息，当阻塞严重时，会触发断线
     *   @param ticker                  订阅的合约编号代码
     *   @param error_info              取消订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次取消订阅的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnUnSubMarketData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     *   查询全市场合约部分静态信息的应答
     *   @attention                     需要使用合约部分静态信息结构体EMTQuoteStaticInfo
     *   @param qsi                     合约部分静态信息结构体
     *   @param error_info              订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnQueryAllTickers(EMTQuoteStaticInfo* qsi, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     *   查询全市场合约完整静态信息的应答
     *   @attention                     需要使用合约完整静态信息结构体EMTQutoFullInfo(沪深两市场静态信息)
     *   @param qfi                     合约完整静态信息结构体
     *   @param error_info              订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnQueryAllTickersFullInfo(EMTQuoteFullInfo* qfi, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     *   查询合约最新指数的应答
     *   @attention                     需要使用最新数据结构体EMTIndexDataStruct
     *   @param index_data              最新指数数据
     *   @param error_info              订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnQueryLatestIndexData(EMTIndexDataStruct* index_data, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     *   查询合约最新现货快照的应答
     *   @attention                     需要使用最新数据结构体EMTMarketDataStruct
     *   @param market_data             最新现货快照数据
     *   @param error_info              订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     *   @param is_last                 是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnQueryLatestMarketData(EMTMarketDataStruct* market_data, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     * 查询最新价
     * @attention                       需要使用最新价结构体EMTTickerPriceInfo
     * @param price_info                最新价格数据
     * @param error_info                订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     * @param is_last                   是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnQueryTickersPriceInfo(EMTTickerPriceInfo* price_info, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     * @brief  查询港股静态信息
     * @attention                       需要使用港股静态信息结构体EMTHKStaticInfo
     * @param  static_info              港股静态信息数据
     * @param  error_info               订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     * @param  is_last                  是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnQueryHKStaticInfo(EMTHKStaticInfo* static_info, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     * @brief  查询股转静态信息
     * @attention                       需要使用股转静态信息结构体EMTBJGZStaticInfo
     * @param  static_info              股转静态信息数据
     * @param  error_info               订阅合约发生错误时的错误信息，当error_info为空，或者error_info.error_id为0时，表明没有错误
     * @param  is_last                  是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnQueryBJGZStaticInfo(EMTBJGZStaticInfo* static_info, EMTRspInfoStruct* error_info, bool is_last) {};

    /**
     * 查询重建回补深市逐笔数据应答
     * @param  rebuild_data             重建数据响应信息
     * @param  error_info               错误信息，服务器响应发生错误的具体错误内容
     * @param  is_last                  是否此次查询的最后一个应答，当为最后一个的时候为true，如果为false，表示还有其他后续消息响应
     */
    virtual void OnRebuildSzData(const EMTRebuildRespData* rebuild_data, const EMTRspInfoStruct* error_info, const bool is_last) {};
};

class QUOTE_API_ QuoteApi {
  public:

    /**
     * @brief  创建QuoteApi
     * @attention                       系统不支持过夜，请确保每天开盘前重新启动
     * @param  log_path                 日志输出目录，请设定一个真实存在的有可写权限的路径
     * @param  log_file_level           文件日志的日志级别
     * @param  log_console_level        控制台日志的日志级别
     * @return 创建出的QuoteApi实例
     */
    static QuoteApi* CreateQuoteApi(const char* log_path, EMQ_LOG_LEVEL log_file_level, EMQ_LOG_LEVEL log_console_level);

    /**
     * @brief  注册回调接口
     * @param  quote_spi                派生自回调接口类的实例，请在登录之前设定
     */
    virtual void RegisterSpi(QuoteSpi* quote_spi) = 0;

    /**
     * @brief  用户登录请求
     * @attention                       此函数为同步阻塞式，不需要异步等待登录成功，当函数返回即可进行后续操作
     * @param  ip                       服务器地址，类似“127.0.0.1”
     * @param  port                     服务器端口号
     * @param  user                     登录用户名
     * @param  pwd                      登录密码
     * @return 创建出的QuoteApi实例
     */
    virtual int32_t Login(const char* ip, const uint16_t port, const char* user, const char* pwd) = 0;

    /**
     * @brief  登出请求
     */
    virtual void Logout() = 0;

    /**
     * @brief  查询回补深市逐笔数据
     * 
     * @attention                       此接口对L1用户不提供服务
     * @param  chno                     回补数据通道号
     * @param  beg_seq                  回补数据起始序号
     * @param  end_seq                  回补数据结束序号
     * @param  request_id               保留字段，填写大于等于0的随机值
     * @return                          请求是否成功 "0"表示请求成功，"-2"表示请求链接被打断失败,发送回补消息失败，可以尝试重新请求 "-3"表示权限校验失败
     */
    virtual int32_t RebuildSzData(const uint32_t chno, const uint64_t beg_seq, const uint64_t end_seq, const uint64_t request_id) = 0;

    /**
     * @brief  设置系统线程绑定的cpu id
     * 
     * @attention                       此函数可不调用,调用需要在登录前调用。id填写 -1 则操作系统自由分配，不进行绑核。
     * @param  recv_cpu_no              接收线程绑定cpu id号 例如绑定cpu 0，可以设置0，绑定cpu 2，可以设置2，建议绑定后面的cpu
     * @param  process_cpu_no           处理线程绑定cpu id号
     * @return
     */
    virtual void SetThreadAffinity(int32_t recv_cpu_no = -1,int32_t process_cpu_no = -1) = 0;

    /**
     *   @brief 设置缓冲区大小
     *   @attention                     设置api内部消息缓存区大小,登录前设置生效
     *   @param buffer_size             缓存区大小，单位MB；默认512MB，最小设置为64MB
     *   @return                        "0"表示设置成功，非"0"表示输入无效启用默认值
     */
    virtual int32_t SetBuffer(size_t buffer_size) = 0;

    /**
     *   @brief 订阅全市场指数快照行情
     *   @attention                     需要与取消订阅全市场指数行情接口配套使用
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        订阅全市场指数快照行情接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int SubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 取消订阅全市场指数快照行情
     *   @attention                     需要与订阅全市场指数行情接口配套使用
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        取消订阅全市场指数快照行情接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int UnSubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 订阅指数快照行情
     *   @attention                     可一次性订阅同一证券交易所的多个指数，无论用户因为何种问题需要重新登录行情服务器，都需要重新订阅
     *   @param tickers                 指数代码数组，注意指数代码必须以"\0"结尾，不包括空格
     *   @param count                   需要订阅行情的指数个数
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        订阅接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int SubscribeIndexData(char* tickers[], int count, EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 取消订阅指数快照行情
     *   @attention                     可一次性取消订阅同一证券交易所的多个指数，无论用户因为何种问题需要重新登录行情服务器，都需要重新订阅
     *   @param tickers                 指数代码数组，注意指数代码必须以"\0"结尾，不包括空格
     *   @param count                   需要订阅行情的指数个数
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        取消订阅接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int UnSubscribeIndexData(char* tickers[], int count, EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 订阅全市场合约快照行情
     *   @attention                     需要与全市场退订行情接口配套使用
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场
     *   @return                        订阅全市场行情接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int SubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 退订全市场合约快照行情
     *   @attention                     需要与全市场订阅行情接口配套使用
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_SHHK表示为沪市港股通，EMQ_EXCHANGE_SZHK表示为深市港股通，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        退订全市场行情接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int UnSubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 订阅快照行情，包括股票，基金，债券，权证和质押式回购
     *   @attention                     可一次性订阅同一证券交易所的多个合约，无论用户因为何种问题需要重新登录行情服务器，都需要重新订阅
     *   @param tickers                 合约代码数组，注意合约代码必须以"\0"结尾，不包括空格
     *   @param count                   需要订阅行情的合约个数
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_SHHK表示为沪市港股通，EMQ_EXCHANGE_SZHK表示为深市港股通，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        订阅接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int SubscribeMarketData(char* tickers[], int count, EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 取消订阅快照行情，包括股票，基金，债券，权证和质押式回购
     *   @attention                     可一次性取消订阅同一证券交易所的多个合约，无论用户因为何种问题需要重新登录行情服务器，都需要重新订阅
     *   @param tickers                 合约代码数组，注意合约代码必须以"\0"结尾，不包括空格
     *   @param count                   需要订阅行情的合约个数
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_SHHK表示为沪市港股通，EMQ_EXCHANGE_SZHK表示为深市港股通，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        取消订阅接口调用是否成功，"0"表示接口调用成功，非"0"表示接口调用出错
     */
    virtual int UnSubscribeMarketData(char* tickers[], int count, EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 获取所有合约的部分静态信息，包括全市场所有合约的部分静态信息
     *   @param exchange_id             交易所代码，支持沪深市场，EMQ_EXCHANGE_SH表示上海全市场，EMQ_EXCHANGE_SZ表示深证全市场
     *   @return                        发送查询请求是否成功，"0"表示发送查询请求成功，非"0"表示发送查询请求不成功
     */
    virtual int QueryAllTickers(EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 获取所有合约的完整静态信息，包括全市场所有合约的完整静态信息
     *   @param exchange_id             交易所代码，支持沪深市场，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场，EMQ_EXCHANGE_SHHK表示为沪市港股通，EMQ_EXCHANGE_SZHK表示为深市港股通，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        发送查询请求是否成功，"0"表示发送查询请求成功，非"0"表示发送查询请求不成功
     */
    virtual int QueryAllTickersFullInfo(EMQ_EXCHANGE_TYPE exchange_id = EMQ_EXCHANGE_TYPE::EMQ_EXCHANGE_UNKNOWN) = 0;

    /**
     *   @brief 获取最新快照信息
     *   @param tickers                 合约ID数组，注意合约代码必须以'\0'结尾，不包含空格
     *   @param count                   合约个数，为0表示查询交易所所有合约
     *   @param ticker_type             合约类型
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场,EMQ_EXCHANGE_SHHK表示为沪市港股通，EMQ_EXCHANGE_SZHK表示为深市港股通，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        发送查询请求是否成功，"0"表示发送查询请求成功，非"0"表示发送查询请求不成功
     */
    virtual int QueryLatestInfo(char* tickers[], int count, EMQ_TICKER_TYPE ticker_type, EMQ_EXCHANGE_TYPE exchange_id) = 0;

    /**
     *   @brief 获取最新价
     *   @param tickers                 合约ID数组，注意合约代码必须以'\0'结尾，不包含空格
     *   @param count                   合约个数，为0表示查询交易所所有合约
     *   @param exchange_id             交易所代码，EMQ_EXCHANGE_SH表示为上海全市场，EMQ_EXCHANGE_SZ表示为深圳全市场,EMQ_EXCHANGE_SHHK表示为沪市港股通，EMQ_EXCHANGE_SZHK表示为深市港股通，EMQ_EXCHANGE_BJGZK表示北交所股转市场
     *   @return                        发送查询请求是否成功，"0"表示发送查询请求成功，非"0"表示发送查询请求不成功
     */
    virtual int QueryTickersPriceInfo(char* tickers[], int count, EMQ_EXCHANGE_TYPE exchange_id) = 0;

    /**
    * @brief 纯虚析构函数
    */
    virtual ~QuoteApi() {};

};

} // namespace API
} // namespace EMQ