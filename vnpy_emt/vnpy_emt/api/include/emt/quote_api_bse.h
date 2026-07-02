/////////////////////////////////////////////////////////////////////////
///@author 东方财富证券股份有限公司
///@file quote_api_bj.h
///@brief 定义北交所极速行情接口
/////////////////////////////////////////////////////////////////////////

#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <vector>
#include "quote_struct_bse.h"
#include "quote_bse_define.h"


namespace EMQ {
namespace API {
namespace BSE {
class QuoteSpiBse{
public:
    /* 以下为北交所行情回调 */

    /**
     *   北交所快照行情通知
     *   @param snap  北交所快照行情数据
     */
    virtual void OnSnapBse(EMQBseSnap *snap) {}
};


#ifndef WINDOWS
#if __GNUC__ >= 4
#pragma GCC visibility push(default)
#endif
#endif

class QuoteApiBse {
public:
    /**
     *   创建 QuoteApiBse 实例
     *   @param save_file_path   日志文件保存路径
     *   @param log_level        日志等级，默认为 EMQ_LOG_LEVEL_DEBUG
     *   @return                 返回创建的 QuoteApiBj 实例
     */
    static QuoteApiBse *CreateQuoteApiBse(const char *save_file_path, EMQ_LOG_LEVEL log_level = EMQ_LOG_LEVEL_DEBUG);

    /**
     *   注册回调接口
     *   @param spi  回调接口指针
     */
    virtual void RegisterSpi(QuoteSpiBse *spi) = 0;

    /**
     *   获取 API 版本信息
     *   @return  返回 API 版本号字符串
     */
    virtual const char *GetApiVersion() = 0;

    /**
     *   设置通道接收配置，同时进行内置系统配置最优检查
     *   @param config  通道配置数组
     *   @param num     通道数量
     *   @return        返回设置结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t SetChannelConfig(EMQLoginConfigBse login_config, EMQUdpConfigBse *config, uint32_t num) = 0;

    /**
     *   启动接口
     *   @return  返回启动结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t Start() = 0;

    /**
     *   停止接口
     *   @return  返回停止结果，0 表示成功，非 0 表示失败
     */
    virtual int32_t Stop() = 0;

    /**
     *   关闭接口，释放资源
     */
    virtual void Release() = 0;


    /**
     *   获取网卡收到行情包的硬件时间戳，单位 ns
     *   仅可在对应的行情 SPI 回调内调用
     *   @param packet  行情数据包
     *   @return        返回硬件接收时间戳，单位为纳秒
     */
    virtual uint64_t GetPacketHardwareRXTs(void *packet) = 0;

protected:
    virtual ~QuoteApiBse() {}
};

#ifndef WINDOWS
#if __GNUC__ >= 4
#pragma GCC visibility pop
#endif
#endif

} // namespace BSE
} // namespace API
} // namespace EMQ