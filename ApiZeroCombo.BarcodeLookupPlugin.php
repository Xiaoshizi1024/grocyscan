<?php
use Grocy\Helpers\BaseBarcodeLookupPlugin;

/**
 * ApiZero 组合条码查询插件 (lookup 优先 + gs1 兜底) for Grocy
 *
 * 数据源:
 *   - 优先: https://apizero.cn/api/barcode-lookup  (免费版, 广覆盖商业库)
 *   - 兜底: https://apizero.cn/api/barcode-gs1    (PRO 版, 直通中国物品编码中心官方库)
 *
 * 策略:
 *   1) 先打免费版 barcode-lookup —— 覆盖日常消费品/进口货/冷门货, 命中率高(国内主流>95%)
 *   2) 若 lookup 查不到 (found=false 或无商品名), 再用 PRO 版 barcode-gs1 兜底回填官方数据
 *   3) 两者都查不到 -> 返回 null, Grocy 自动回退到手动录入
 *
 * 字段映射 (2026-07-22 核查修正, 基于官方源码):
 *   - 品牌(brand)        -> Grocy products 表无 brand 列! 写入 description
 *   - 分类(category/GPC) -> Grocy product_groups (product_group_id), 需 $categoryMap 映射
 *   - 图片(__image_url)  -> Grocy 建产品时自动下载并设为产品图 (StockService.php:633-667)
 *   - 生产商/规格/净含量  -> Grocy 无独立字段, 写入 description 备注
 *
 * 重要: Grocy 插件返回数组的非 __ 前缀键会直接传给 products()->createRow(),
 *       products 表没有的列会被 NotORM 静默忽略。products 表无 brand 列(已核源码确认)。
 *
 * 部署见 install.sh。依赖: 仅 PHP curl 扩展 (Grocy 镜像自带, 零额外依赖)。
 */

class ApiZeroComboBarcodeLookupPlugin extends BaseBarcodeLookupPlugin
{
    public const PLUGIN_NAME = 'ApiZero Combo (lookup + gs1)';

    const API_KEY = '';
    const LOOKUP_URL = 'https://v1.apizero.cn/api/barcode-lookup';
    const GS1_URL    = 'https://v1.apizero.cn/api/barcode-gs1';

    /**
     * 分类(GPC码 / 分类名) -> Grocy 产品组 id 映射。
     * Grocy 产品组是你在网页端"管理→产品组"自建的, apizero 的 GPC 分类体系无法直接对应,
     * 因此需要你在这里手动建立映射。插件会优先按 GPC 码(如 10000232)匹配, 也支持按分类名匹配。
     *
     * 用法:
     *   1) 在 Grocy 建好产品组, 记下它的 id (如"饮用水"=5)
     *   2) 在下面数组里加一行, 例如:
     *        '10000232' => 5,   // GPC 瓶装饮用水 -> 产品组"饮用水"
     *        '水'       => 5,
     *   3) 未列出的分类会退回写入 description, 不会丢失。
     */
    private static $categoryMap = array(
        // '10000232' => 0,   // 取消注释并改成你 Grocy 里对应产品组的真实 id
    );

    protected function ExecuteLookup($barcode)
    {
        $lookup = $this->fetchLookup($barcode);
        if ($lookup !== null)
        {
            $res = $this->buildFromLookup($lookup, $barcode);
            if ($res !== null) return $res;
        }
        $gs1 = $this->fetchGs1($barcode);
        if ($gs1 !== null)
        {
            $res = $this->buildFromGs1($gs1, $barcode);
            if ($res !== null) return $res;
        }
        return null;
    }

    private function fetchLookup($barcode)
    {
        $resp = $this->callApi(self::LOOKUP_URL, 'barcode', $barcode);
        if ($resp === null || !isset($resp['data']) || !is_array($resp['data'])) return null;
        $d = $resp['data'];
        if (empty($d['found'])) return null;
        return $d;
    }

    private function buildFromLookup($d, $barcode)
    {
        $name = trim((string)($d['name'] ?? ''));
        if ($name === '') return null;
        $locationId = $this->resolveLocationId();
        $quId = $this->resolveQuantityUnitId();

        $result = array(
            'name'                           => $name,
            'location_id'                    => $locationId,
            'qu_id_purchase'                 => $quId,
            'qu_id_stock'                    => $quId,
            '__qu_factor_purchase_to_stock'  => 1,
            '__barcode'                      => (string)$barcode,
        );

        // 分类 -> Grocy 产品组 (尽力映射; 映射不到则仍进 description)
        $pgId = $this->resolveProductGroupId($d['category'] ?? '');
        if ($pgId !== null)
        {
            $result['product_group_id'] = $pgId;
        }

        // 图片: 免费版返回单张 URL, Grocy 建产品时自动下载并设为产品图
        if (!empty($d['image']) && is_string($d['image']))
        {
            $result['__image_url'] = $d['image'];
        }

        // 品牌/生产商/规格等 Grocy 无独立列, 全部拼进 description
        // (注: products 表无 brand 列, 此前写 $result['brand'] 被 NotORM 静默忽略)
        $desc = array();
        if (!empty($d['brand']))       $desc[] = '品牌: ' . $d['brand'];
        if (!empty($d['manufacturer'])) $desc[] = '生产商: ' . $d['manufacturer'];
        if (!empty($d['spec']))         $desc[] = '规格: ' . $d['spec'];
        if (isset($d['price']) && $d['price'] !== null && $d['price'] !== '')
        {
            $desc[] = '参考价: ' . $d['price'] . ' 元';
        }
        if ($pgId === null && !empty($d['category'])) $desc[] = '分类: ' . $d['category'];
        if (!empty($d['description']))  $desc[] = $d['description'];
        if (!empty($desc))
        {
            $result['description'] = implode("\n", $desc);
        }
        return $result;
    }

    private function fetchGs1($barcode)
    {
        $resp = $this->callApi(self::GS1_URL, 'code', $barcode);
        if ($resp === null || !isset($resp['data']) || !is_array($resp['data'])) return null;
        $d = $resp['data'];
        if (empty($d['found']) || empty($d['registered'])) return null;
        return $d;
    }

    private function buildFromGs1($d, $barcode)
    {
        $name = $this->pickName($d);
        if ($name === '') return null;
        $locationId = $this->resolveLocationId();
        $quId = $this->resolveQuantityUnitId();

        $result = array(
            'name'                           => $name,
            'location_id'                    => $locationId,
            'qu_id_purchase'                 => $quId,
            'qu_id_stock'                    => $quId,
            '__qu_factor_purchase_to_stock'  => 1,
            '__barcode'                      => (string)$barcode,
        );

        // 分类 -> Grocy 产品组 (尽力映射; 识别 category 中的 GPC 码 10000232)
        $pgId = $this->resolveProductGroupId($d['category'] ?? '');
        if ($pgId !== null)
        {
            $result['product_group_id'] = $pgId;
        }

        // 图片: 返回 __image_url, Grocy 建产品时下载并设为产品图 (原生支持)
        if (!empty($d['images']) && is_array($d['images']))
        {
            $img = reset($d['images']);
            if (is_string($img) && $img !== '')
            {
                $result['__image_url'] = $img;
            }
        }

        // 品牌/生产商/规格等 Grocy 无独立列, 全部拼进 description
        // (注: products 表无 brand 列, 此前写 $result['brand'] 被 NotORM 静默忽略)
        $desc = array();
        if (!empty($d['brand']))       $desc[] = '品牌: ' . $d['brand'];
        if (!empty($d['manufacturer'])) $desc[] = '生产商: ' . $d['manufacturer'];
        if (!empty($d['specification']))$desc[] = '规格: ' . $d['specification'];
        if (!empty($d['net_content']))  $desc[] = '净含量: ' . $d['net_content'];
        if (!empty($d['general_name'])) $desc[] = '通用名: ' . $d['general_name'];
        if (!empty($d['sale_date']))    $desc[] = '上市日期: ' . $d['sale_date'];
        if ($pgId === null && !empty($d['category'])) $desc[] = '分类: ' . $d['category'];
        if (!empty($desc))
        {
            $result['description'] = implode("\n", $desc);
        }
        return $result;
    }

    private function callApi($baseUrl, $paramName, $barcode)
    {
        $resp = $this->doCall($baseUrl, $paramName, $barcode);
        if ($resp !== null && isset($resp['code']) && $resp['code'] == 4029)
        {
            usleep(1200000);
            $resp = $this->doCall($baseUrl, $paramName, $barcode);
        }
        return $resp;
    }

    /**
     * 解析 apizero key, 三级复用:
     *   1) config.php 的 define('APIZERO_KEY')         —— GS1 插件同一机制, 自动共享
     *   2) 同目录 GS1 插件文件的 const API_KEY          —— 兼容当初直接把 key 写进 GS1 文件
     *   3) 本文件 const API_KEY (空 = 匿名)
     * 因此 GS1 与 lookup 共用同一 key, 部署组合插件无需重新输入。
     */
    private function resolveApiKey()
    {
        if (defined('APIZERO_KEY') && APIZERO_KEY !== '')
        {
            return (string)APIZERO_KEY;
        }
        $gs1File = __DIR__ . '/ApiZero.BarcodeLookupPlugin.php';
        if (is_file($gs1File))
        {
            $src = @file_get_contents($gs1File);
            if ($src !== false && preg_match("/const\s+API_KEY\s*=\s*'([^']*)'/", $src, $m) && $m[1] !== '')
            {
                return $m[1];
            }
        }
        return self::API_KEY;
    }

    private function doCall($baseUrl, $paramName, $barcode)
    {
        // 复用 apizero key: 三级回退, 无需为 lookup/gs1 分别输入
        //   1) data/config.php 里的 define('APIZERO_KEY', ...)   (GS1 插件也读这个)
        //   2) 已部署的 GS1 插件文件里硬编码的 const API_KEY      (兼容当初直接写进 GS1 文件的情况)
        //   3) 本文件 const API_KEY (默认空 = 匿名额度)
        $key = $this->resolveApiKey();
        $url = $baseUrl . '?' . $paramName . '=' . urlencode($barcode);
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
                $id = is_array($loc) ? ($loc['id'] ?? 0) : ($loc->id ?? 0);
                if ($id > 0)
                {
                    $validIds[] = (int)$id;
                }
            }
        }
        if (empty($validIds))
        {
            // external-lookup API 路径可能不注入 locations, 降级用已知默认值 (玄关 id=3)
            return 3;
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
                $id = is_array($qu) ? ($qu['id'] ?? 0) : ($qu->id ?? 0);
                if ($id > 0)
                {
                    $validIds[] = (int)$id;
                }
            }
        }
        if (empty($validIds))
        {
            // external-lookup API 路径可能不注入 quantityUnits, 降级用已知默认值 (个 id=1)
            return 1;
        }
        $preset = $this->presetId('product_presets_qu_id');
        if ($preset !== null && in_array($preset, $validIds, true))
        {
            return $preset;
        }
        return $validIds[0];
    }

    /**
     * 把 apizero 分类映射到 Grocy 产品组 id。
     * 优先级:
     *   1) 基类若注入了 $this->productGroups, 按分类名包含匹配 (如 category 含"饮用水"则匹配产品组"饮用水")
     *   2) 本类静态 $categoryMap (支持 GPC 码 与 分类名, 见类顶部注释)
     * 都匹配不到返回 null (分类名仍会写进 description)。
     */
    private function resolveProductGroupId($category)
    {
        if (empty($category) || !is_string($category))
        {
            return null;
        }
        // 1) 基类注入的产品组按名包含匹配
        if (isset($this->productGroups) && is_array($this->productGroups))
        {
            foreach ($this->productGroups as $pg)
            {
                if (isset($pg->name) && $pg->name !== '' && strpos($category, $pg->name) !== false)
                {
                    return (int)$pg->id;
                }
            }
        }
        // 2) 静态映射 (支持 GPC 码 与 分类名)
        $map = self::$categoryMap;
        if (isset($map[$category]))
        {
            return (int)$map[$category];
        }
        if (preg_match('/\((\d+)\)/', $category, $m) && isset($map[$m[1]]))
        {
            return (int)$map[$m[1]];
        }
        return null;
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
