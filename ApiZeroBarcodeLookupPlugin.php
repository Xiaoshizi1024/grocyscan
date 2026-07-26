<?php
use Grocy\Helpers\BaseBarcodeLookupPlugin;

/**
 * ApiZero (barcode-gs1) Barcode Lookup Plugin for Grocy — 路径X 版
 * 数据源: https://apizero.cn/api/barcode-gs1  (直通中国物品编码中心官方注册库)
 *
 * 路径X 策略（先完成再完美）:
 *   - 标准字段(name / location_id / qu_id_* / __barcode) + 图片(__image_url)
 *     由 Grocy 后端 StockService 原生处理: 图片会被自动下载存为产品图。
 *   - apizero 的 品牌/分类/生产商/规格/净含量/通用名/上市日期
 *     拼进 description 标准字段, 后端原生写入产品描述 (扫码即带出)。
 *   - 如需"自定义字段自动填", 见路径Y(改 StockService.php 把 __userfields 写 userfield_values)。
 *
 * 重要: Grocy 基类 BaseBarcodeLookupPlugin::Lookup() 强制要求输出包含以下 6 个键,
 * 且 location_id / qu_id_purchase / qu_id_stock 必须是 Grocy 中真实存在的 id,
 * 否则会报 "does not provide needed property" 或 "not a valid ... id"。
 * 因此本插件:
 *   1) 永远带齐这 6 个键;
 *   2) 只取 $this->locations / $this->quantityUnits 中真实存在的 id;
 *   3) 若 Grocy 中一个位置/数量单位都没有(扫码服务会自动建默认), 则抛清晰中文错误。
 *
 * 部署:
 *   1) 把本文件放到 Grocy data/plugins/, 命名为 ApiZeroBarcodeLookupPlugin.php
 *   2) data/config.php 里:  Setting('STOCK_BARCODE_LOOKUP_PLUGIN', 'ApiZeroBarcodeLookupPlugin');
 *   3) (可选) data/config.php 末尾加:  define('APIZERO_KEY', 'sk_xxx');  提升每日额度
 *   4) 重启 Grocy 容器
 *
 * 依赖: 仅 PHP curl 扩展 (Grocy 镜像自带, 零额外依赖)。
 */

class ApiZeroBarcodeLookupPlugin extends BaseBarcodeLookupPlugin
{
    public const PLUGIN_NAME = 'ApiZero GS1 China';

    // 留空 = 匿名额度. 也可在 data/config.php 里 define('APIZERO_KEY', 'sk_xxx') 提升额度
    const API_KEY = '';
    const API_URL = 'https://v1.apizero.cn/api/barcode-gs1';

    protected function ExecuteLookup($barcode)
    {
        $data = $this->fetchWithRetry($barcode);
        if ($data === null || empty($data['found']) || empty($data['registered']))
        {
            // 查不到(进口/未登记/限流): 交给 Grocy 手动录入
            return null;
        }

        $name = $this->pickName($data);
        if ($name === '')
        {
            return null;
        }

        // 永远带齐基类要求的 6 个键; 位置/单位取真实存在的 id, 没有就抛清晰错误
        $locationId = $this->resolveLocationId();
        $quId       = $this->resolveQuantityUnitId();

        $result = array(
            'name'                           => $name,
            'location_id'                    => $locationId,
            'qu_id_purchase'                 => $quId,
            'qu_id_stock'                    => $quId,
            '__qu_factor_purchase_to_stock'  => 1,
            '__barcode'                      => (string)$barcode,
        );

        // 图片: 返回 __image_url, Grocy 后端会自动下载并设为产品图 (原生支持, 无需插件自己下)
        if (!empty($data['images']) && is_array($data['images']))
        {
            $img = reset($data['images']);
            if (is_string($img) && $img !== '')
            {
                $result['__image_url'] = $img;
            }
        }

        // 路径X: 把 apizero 额外信息拼进 description (后端原生写入产品描述)
        $descLines = array();
        if (!empty($data['brand']))        $descLines[] = '品牌: ' . $data['brand'];
        if (!empty($data['category']))     $descLines[] = '分类: ' . $data['category'];
        if (!empty($data['manufacturer'])) $descLines[] = '生产商: ' . $data['manufacturer'];
        if (!empty($data['specification']))$descLines[] = '规格: ' . $data['specification'];
        if (!empty($data['net_content']))  $descLines[] = '净含量: ' . $data['net_content'];
        if (!empty($data['general_name'])) $descLines[] = '通用名: ' . $data['general_name'];
        if (!empty($data['sale_date']))    $descLines[] = '上市日期: ' . $data['sale_date'];
        if (!empty($descLines))
        {
            $result['description'] = implode("\n", $descLines);
        }

        return $result;
    }

    private function fetchWithRetry($barcode)
    {
        $resp = $this->callApi($barcode);
        // 限流(4029)时等 1.2s 重试一次 (接口 QPS=1)
        if ($resp !== null && isset($resp['code']) && $resp['code'] == 4029)
        {
            usleep(1200000);
            $resp = $this->callApi($barcode);
        }
        if ($resp === null || !isset($resp['data']) || !is_array($resp['data']))
        {
            return null;
        }
        return $resp['data'];
    }

    private function callApi($barcode)
    {
        // 优先读 data/config.php 里 define('APIZERO_KEY', ...) 的 key, 否则用本文件常量
        $key = self::API_KEY;
        if (defined('APIZERO_KEY') && APIZERO_KEY !== '')
        {
            $key = (string)APIZERO_KEY;
        }

        $url = self::API_URL . '?code=' . urlencode($barcode);
        if ($key !== '')
        {
            $url .= '&key=' . urlencode($key);
        }

        $ch = curl_init($url);
        curl_setopt_array($ch, array(
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 15,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_USERAGENT      => 'Grocy-ApiZero-Plugin',
            // N1 容器 CA 证书可能不全, 跳过 SSL 校验以保证可用 (内网家用场景可接受)
            CURLOPT_SSL_VERIFYPEER => false,
            CURLOPT_SSL_VERIFYHOST => false,
        ));
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($response === false || $httpCode !== 200)
        {
            return null;
        }

        $json = json_decode($response, true);
        return is_array($json) ? $json : null;
    }

    private function pickName($data)
    {
        if (!empty($data['name']))
        {
            return $data['name'];
        }
        $parts = array_filter(array(
            isset($data['brand']) ? $data['brand'] : '',
            isset($data['general_name']) ? $data['general_name'] : '',
        ));
        return implode(' ', $parts);
    }

    /**
     * 返回 Grocy 中真实存在的位置 id; 没有可用位置则抛清晰中文错误。
     */
    private function resolveLocationId()
    {
        $validIds = array();
        if (!empty($this->locations))
        {
            foreach ($this->locations as $loc)
            {
                if (isset($loc->id) && $loc->id > 0)
                {
                    $validIds[] = (int)$loc->id;
                }
            }
        }
        if (empty($validIds))
        {
            throw new \Exception('Grocy 中还没有任何"位置"。请在网页端 管理→位置 至少添加一个(如"储藏室")，或等扫码服务自动创建默认位置后重试');
        }
        $preset = $this->presetId('product_presets_location_id');
        if ($preset !== null && in_array($preset, $validIds, true))
        {
            return $preset;
        }
        return $validIds[0];
    }

    /**
     * 返回 Grocy 中真实存在的数量单位 id; 没有可用数量单位则抛清晰中文错误。
     */
    private function resolveQuantityUnitId()
    {
        $validIds = array();
        if (!empty($this->quantityUnits))
        {
            foreach ($this->quantityUnits as $qu)
            {
                if (isset($qu->id) && $qu->id > 0)
                {
                    $validIds[] = (int)$qu->id;
                }
            }
        }
        if (empty($validIds))
        {
            throw new \Exception('Grocy 中还没有任何"数量单位"。请在网页端 管理→数量单位 至少添加一个(如"个")，或等扫码服务自动创建默认单位后重试');
        }
        $preset = $this->presetId('product_presets_qu_id');
        if ($preset !== null && in_array($preset, $validIds, true))
        {
            return $preset;
        }
        return $validIds[0];
    }

    private function presetId($key)
    {
        $v = null;
        if (function_exists('DefaultUserSetting'))
        {
            $v = DefaultUserSetting($key, -1);
        }
        elseif (isset($this->userSettings) && isset($this->userSettings[$key]))
        {
            $v = $this->userSettings[$key];
        }
        if ($v !== null && $v > 0)
        {
            return (int)$v;
        }
        return null;
    }
}
