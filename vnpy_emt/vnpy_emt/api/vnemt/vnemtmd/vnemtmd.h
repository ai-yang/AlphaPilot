// Minimal-surface EMT quote (market data) binding for the new EMQ::API SDK
// (quote_api.h, API_VERSION >= 2.19). Rewritten because the vendor renamed the
// quote namespace EMT::API -> EMQ::API and changed CreateQuoteApi/Login, so the
// old 2.7.1-era binding cannot compile against these headers.
//
// Python-visible surface is kept as close to the old vnemtmd as possible
// (class MdApi, module vnemtmd, dict-based callbacks) so vnpy_emt's gateway
// only needs its call sites (createQuoteApi / login) updated.

#ifdef WIN32
//#include "stdafx.h"
#endif

#include "vnemt.h"
#include "pybind11/pybind11.h"
#include "emt/quote_api.h"


using namespace pybind11;
using namespace EMQ::API;


class MdApi : public QuoteSpi
{
private:
	QuoteApi* api = NULL;
	bool active = false;
	int last_error_id = 0;
	string last_error_msg = "";

public:
	MdApi()
	{
	};

	~MdApi()
	{
		if (this->active)
		{
			this->exit();
		}
	};

	//-------------------------------------------------------------------------------------
	// C++ SPI overrides (new EMQ::API::QuoteSpi surface)
	//-------------------------------------------------------------------------------------

	virtual void OnError(const EMTRspInfoStruct* error_info);

	virtual void OnDepthMarketData(EMTMarketDataStruct* market_data, int64_t bid1_qty[], int32_t bid1_count, int32_t max_bid1_count, int64_t ask1_qty[], int32_t ask1_count, int32_t max_ask1_count);

	virtual void OnIndexData(EMTIndexDataStruct* index_data);

	virtual void OnSubMarketData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last);

	virtual void OnUnSubMarketData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last);

	virtual void OnSubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info);

	virtual void OnUnSubscribeAllMarketData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info);

	virtual void OnSubIndexData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last);

	virtual void OnUnSubIndexData(EMTSpecificTickerStruct* ticker, EMTRspInfoStruct* error_info, bool is_last);

	virtual void OnSubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info);

	virtual void OnUnSubscribeAllIndexData(EMQ_EXCHANGE_TYPE exchange_id, EMTRspInfoStruct* error_info);

	virtual void OnQueryAllTickers(EMTQuoteStaticInfo* qsi, EMTRspInfoStruct* error_info, bool is_last);

	virtual void OnQueryAllTickersFullInfo(EMTQuoteFullInfo* qfi, EMTRspInfoStruct* error_info, bool is_last);

	virtual void OnQueryTickersPriceInfo(EMTTickerPriceInfo* price_info, EMTRspInfoStruct* error_info, bool is_last);

	//-------------------------------------------------------------------------------------
	// Python-facing virtuals (dict payloads)
	//-------------------------------------------------------------------------------------

	// NOTE: the new EMQ quote SPI has no disconnect callback; onDisconnected is
	// kept so existing gateway code stays valid, but it never fires from C++.
	virtual void onDisconnected(int reason) {};

	virtual void onError(const dict& data) {};

	virtual void onDepthMarketData(const dict& data) {};

	virtual void onIndexData(const dict& data) {};

	virtual void onSubMarketData(const dict& data, const dict& error, bool is_last) {};

	virtual void onUnSubMarketData(const dict& data, const dict& error, bool is_last) {};

	virtual void onSubscribeAllMarketData(int exchange_id, const dict& error) {};

	virtual void onUnSubscribeAllMarketData(int exchange_id, const dict& error) {};

	virtual void onSubIndexData(const dict& data, const dict& error, bool is_last) {};

	virtual void onUnSubIndexData(const dict& data, const dict& error, bool is_last) {};

	virtual void onSubscribeAllIndexData(int exchange_id, const dict& error) {};

	virtual void onUnSubscribeAllIndexData(int exchange_id, const dict& error) {};

	virtual void onQueryAllTickers(const dict& data, const dict& error, bool is_last) {};

	virtual void onQueryAllTickersFullInfo(const dict& data, const dict& error, bool is_last) {};

	virtual void onQueryTickersPriceInfo(const dict& data, const dict& error, bool is_last) {};

	//-------------------------------------------------------------------------------------
	// Request methods
	//-------------------------------------------------------------------------------------

	void createQuoteApi(string log_path, int log_file_level, int log_console_level);

	void init();

	void release();

	int exit();

	int login(string ip, int port, string user, string password);

	int logout();

	int subscribeMarketData(string ticker, int count, int exchange_id);

	int unSubscribeMarketData(string ticker, int count, int exchange_id);

	int subscribeAllMarketData(int exchange_id);

	int unSubscribeAllMarketData(int exchange_id);

	int subscribeIndexData(string ticker, int count, int exchange_id);

	int unSubscribeIndexData(string ticker, int count, int exchange_id);

	int subscribeAllIndexData(int exchange_id);

	int unSubscribeAllIndexData(int exchange_id);

	int queryAllTickers(int exchange_id);

	int queryAllTickersFullInfo(int exchange_id);

	int queryTickersPriceInfo(string ticker, int count, int exchange_id);

	// Synthesized from the last OnError / failed login (the new quote API has
	// no GetApiLastError); keeps the gateway's failure path working.
	dict getApiLastError();
};
