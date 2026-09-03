// skinchanger.cpp - internal CS2 skin changer (injected DLL).
// Reads C:\cs2py_skin.txt (lines: "defIndex paintKit seed wear") and applies
// the configured skin to the local player's active weapon using the game's own
// SetAttributeValueByName + UpdateSkin (in-process, so it renders correctly).
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstdarg>
#include <cstring>
#include <thread>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <mutex>

// Offsets (current cs2-dumper dump)
static constexpr uintptr_t OFF_DW_LOCAL_PLAYER_PAWN = 37511784;
static constexpr uintptr_t OFF_DW_ENTITY_LIST      = 39260704;
static constexpr uintptr_t OFF_M_PWEAPONSERVICES   = 4616;
static constexpr uintptr_t OFF_M_HACTIVEWEAPON     = 96;
static constexpr uintptr_t OFF_M_ATTRIBUTEMANAGER  = 4520;
static constexpr uintptr_t OFF_M_ITEM              = 80;
static constexpr uintptr_t OFF_M_ITEMDEFINDEX      = 442;
static constexpr uintptr_t OFF_M_ENTITYQUALITY     = 444;
static constexpr uintptr_t OFF_M_ITEMID            = 456;
static constexpr uintptr_t OFF_M_ITEMIDHIGH        = 464;
static constexpr uintptr_t OFF_M_ITEMIDLOW         = 468;
static constexpr uintptr_t OFF_M_ACCOUNTID         = 472;
static constexpr uintptr_t OFF_M_BDISALLOWSOC      = 489;
static constexpr uintptr_t OFF_M_BINITIALIZED      = 488;
static constexpr uintptr_t OFF_M_BRESTORECUSTOM    = 440;
static constexpr uintptr_t OFF_M_OWNERXUIDLOW      = 5752;
static constexpr uintptr_t OFF_M_OWNERXUIDHIGH     = 5756;
static constexpr uintptr_t OFF_M_FALLBACKPAINTKIT  = 5760;
static constexpr uintptr_t OFF_M_FALLBACKSEED      = 5764;
static constexpr uintptr_t OFF_M_FALLBACKWEAR      = 5768;
static constexpr uintptr_t OFF_M_FALLBACKSTATTRAK  = 5772;
static constexpr uintptr_t OFF_M_PGAMESCENENODE    = 816;
static constexpr uintptr_t OFF_M_MODELSTATE        = 320;
static constexpr uintptr_t OFF_M_MESHGROUPMASK     = 520;
static constexpr uintptr_t OFF_M_HHUDMODELARMS     = 7044;

static char g_configPath[MAX_PATH] = { 0 };
static char g_logPath[MAX_PATH] = { 0 };

static void ResolveUserPaths() {
    if (g_configPath[0]) return;  // already resolved
    char up[MAX_PATH] = { 0 };
    DWORD n = GetEnvironmentVariableA("USERPROFILE", up, MAX_PATH);
    if (!n || n >= MAX_PATH) strcpy_s(up, "C:\\Users\\Public");
    snprintf(g_configPath, MAX_PATH, "%s\\cs2py_skin.txt", up);
    snprintf(g_logPath, MAX_PATH, "%s\\cs2py_dll.log", up);
}

static void DllLog(const char* fmt, ...) {
    ResolveUserPaths();
    FILE* f = nullptr;
    if (fopen_s(&f, g_logPath, "a") != 0 || !f) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    fprintf(f, "%02d:%02d:%02d.%03d ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fprintf(f, "\n");
    fclose(f);
}

struct SkinCfg { int paint = 0; int seed = 0; float wear = 0.0f; int meshMask = 1; std::string model; };
static std::vector<std::pair<uint16_t, SkinCfg>> g_skins;
static std::mutex g_mtx;

using SetAttrFn = void(__fastcall*)(void*, const char*, float);
using UpdateSkinFn = void(__fastcall*)(void*, bool);
using UpdateCompFn = void(__fastcall*)(void*, bool);
using UpdateCompSetFn = void(__fastcall*)(void*, bool);
using SetMaskFn = void(__fastcall*)(void*, uint64_t);
using SetModelFn = void(__fastcall*)(void*, const char*);
using UpdateSubclassFn = void(__fastcall*)(void*);
using UpdateWeaponVmFn = void(__fastcall*)(void*);
static SetAttrFn g_setAttr = nullptr;
static UpdateSkinFn g_updateSkin = nullptr;
static UpdateCompFn g_updateComp = nullptr;
static UpdateCompSetFn g_updateCompSet = nullptr;
static SetMaskFn g_setMask = nullptr;
static SetModelFn g_setModel = nullptr;
static UpdateSubclassFn g_updateSubclass = nullptr;
static UpdateWeaponVmFn g_updateWeaponVm = nullptr;

static uintptr_t PatternScan(const char* module, const char* pattern) {
    HMODULE mod = GetModuleHandleA(module);
    if (!mod) return 0;
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(mod);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(reinterpret_cast<uint8_t*>(mod) + dos->e_lfanew);
    uint8_t* base = reinterpret_cast<uint8_t*>(mod);
    size_t size = nt->OptionalHeader.SizeOfImage;
    std::vector<uint8_t> pat;
    std::vector<bool> mask;
    std::istringstream ss(pattern);
    std::string tok;
    while (ss >> tok) {
        if (tok == "?") { pat.push_back(0); mask.push_back(false); }
        else { pat.push_back(static_cast<uint8_t>(strtoul(tok.c_str(), nullptr, 16))); mask.push_back(true); }
    }
    for (size_t i = 0; i + pat.size() <= size; ++i) {
        bool ok = true;
        for (size_t j = 0; j < pat.size(); ++j) {
            if (mask[j] && base[i + j] != pat[j]) { ok = false; break; }
        }
        if (ok) return reinterpret_cast<uintptr_t>(base + i);
    }
    return 0;
}

static uintptr_t ScanCall(const char* pattern) {
    uintptr_t call = PatternScan("client.dll", pattern);
    if (!call) return 0;
    int32_t rel = *reinterpret_cast<int32_t*>(call + 1);
    return call + 5 + rel;
}

static void ResolveFunctions() {
    if (g_setAttr && g_updateSkin && g_updateComp && g_updateCompSet) return;
    // SetAttributeValueByName: CALL instruction; resolve rel32.
    uintptr_t call = PatternScan("client.dll", "E8 ? ? ? ? 66 41 0F 6E D4");
    if (call) {
        int32_t rel = *reinterpret_cast<int32_t*>(call + 1);
        g_setAttr = reinterpret_cast<SetAttrFn>(call + 5 + rel);
    }
    // C_CSWeaponBase::UpdateSkin: function prologue.
    g_updateSkin = reinterpret_cast<UpdateSkinFn>(PatternScan("client.dll",
        "48 89 5C 24 08 57 48 83 EC 20 8B DA 48 8B F9 E8 ? ? ? ? F6 C3 01 74 0A"));
    // UpdateCompositeMaterial: prefer the CALL pattern, then the direct prologue.
    g_updateComp = reinterpret_cast<UpdateCompFn>(ScanCall("E8 ? ? ? ? 48 8D 8B ? ? ? ? 48 89 BC 24"));
    if (!g_updateComp)
        g_updateComp = reinterpret_cast<UpdateCompFn>(PatternScan("client.dll",
            "48 89 5C 24 10 48 89 6C 24 18 48 89 74 24 20 57 41 56 41 57 48 83 EC 20 44 0F B6 F2"));
    // UpdateCompositeMaterialSet.
    g_updateCompSet = reinterpret_cast<UpdateCompSetFn>(PatternScan("client.dll",
        "40 55 53 41 57 48 8D AC 24 00 FE ? ?"));
    // SetMeshGroupMask (game function; does the mesh refresh we need).
    g_setMask = reinterpret_cast<SetMaskFn>(PatternScan("client.dll",
        "48 89 5C 24 ? 48 89 74 24 ? 57 48 83 EC ? 48 8D 99 ? ? ? ? 48 8B 71"));
    // SetModel (for the knife model swap).
    g_setModel = reinterpret_cast<SetModelFn>(PatternScan("client.dll",
        "40 53 48 83 EC ? 48 8B D9 4C 8B C2 48 8B 0D ? ? ? ? 48 8D 54 24 40"));
    // UpdateSubclass + UpdateWeaponViewModel (knife animation class).
    g_updateSubclass = reinterpret_cast<UpdateSubclassFn>(PatternScan("client.dll",
        "4C 8B DC 53 48 81 EC ? ? ? ? 48 8B 41"));
    g_updateWeaponVm = reinterpret_cast<UpdateWeaponVmFn>(PatternScan("client.dll",
        "40 53 48 83 EC 20 48 8B D9 E8 ? ? ? ? 48 83 BB 88 03 00 00 00"));

    DllLog("resolve: setAttr=%p updateSkin=%p updateComp=%p updateCompSet=%p setMask=%p setModel=%p updateSubclass=%p updateWeaponVm=%p",
        (void*)g_setAttr, (void*)g_updateSkin, (void*)g_updateComp, (void*)g_updateCompSet,
        (void*)g_setMask, (void*)g_setModel, (void*)g_updateSubclass, (void*)g_updateWeaponVm);
}

static void ReadConfig() {
    std::lock_guard<std::mutex> lock(g_mtx);
    g_skins.clear();
    ResolveUserPaths();
    std::ifstream f(g_configPath);
    if (!f) return;
    int def = 0, paint = 0, seed = 0, mesh = 1;
    float wear = 0.0f;
    std::string model;
    while (f >> def >> paint >> seed >> wear >> mesh >> model) {
        if (model == "-") model.clear();
        g_skins.push_back({ static_cast<uint16_t>(def), { paint, seed, wear, mesh, model } });
    }
}

static uintptr_t ResolveEntity(uintptr_t client, uint32_t handle) {
    if (!handle || handle == 0xFFFFFFFFu) return 0;
    uintptr_t entityList = *reinterpret_cast<uintptr_t*>(client + OFF_DW_ENTITY_LIST);
    uintptr_t listEntry = *reinterpret_cast<uintptr_t*>(entityList + 0x8 * ((handle & 0x7FFF) >> 9) + 0x10);
    if (!listEntry) return 0;
    return *reinterpret_cast<uintptr_t*>(listEntry + 0x70 * (handle & 0x1FF));
}

static void ApplySkin(uintptr_t weapon, const SkinCfg& cfg, uint16_t defIndex) {
    uintptr_t itemView = weapon + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM;
    uint32_t accountId = *reinterpret_cast<uint32_t*>(weapon + OFF_M_OWNERXUIDLOW);
    if (!accountId) accountId = 1;

    *reinterpret_cast<uint8_t*>(itemView + OFF_M_BDISALLOWSOC) = 1;
    *reinterpret_cast<uint8_t*>(itemView + OFF_M_BRESTORECUSTOM) = 1;
    *reinterpret_cast<uint8_t*>(itemView + OFF_M_BINITIALIZED) = 1;
    *reinterpret_cast<uint32_t*>(itemView + OFF_M_ACCOUNTID) = accountId;
    *reinterpret_cast<uint16_t*>(itemView + OFF_M_ITEMDEFINDEX) = defIndex;
    *reinterpret_cast<uint32_t*>(itemView + OFF_M_ITEMIDHIGH) = 0xFFFFFFFFu;
    *reinterpret_cast<uint32_t*>(itemView + OFF_M_ITEMIDLOW) = 0;
    *reinterpret_cast<uint64_t*>(itemView + OFF_M_ITEMID) = 0xFFFFFFFF00000000ull;

    *reinterpret_cast<uint32_t*>(weapon + OFF_M_OWNERXUIDLOW) = accountId;
    *reinterpret_cast<uint32_t*>(weapon + OFF_M_OWNERXUIDHIGH) = 0;
    *reinterpret_cast<int32_t*>(weapon + OFF_M_FALLBACKPAINTKIT) = cfg.paint;
    *reinterpret_cast<int32_t*>(weapon + OFF_M_FALLBACKSEED) = cfg.seed;
    *reinterpret_cast<float*>(weapon + OFF_M_FALLBACKWEAR) = cfg.wear;
    *reinterpret_cast<int32_t*>(weapon + OFF_M_FALLBACKSTATTRAK) = -1;

    // Mesh group mask via the game's own setter (does the mesh refresh).
    if (g_setMask) {
        uintptr_t wSceneNode = *reinterpret_cast<uintptr_t*>(weapon + OFF_M_PGAMESCENENODE);
        if (wSceneNode) g_setMask(reinterpret_cast<void*>(wSceneNode), static_cast<uint64_t>(cfg.meshMask));
    }

    if (g_setAttr) {
        g_setAttr(reinterpret_cast<void*>(itemView), "set item texture prefab", static_cast<float>(cfg.paint));
        g_setAttr(reinterpret_cast<void*>(itemView), "set item texture wear", cfg.wear);
        g_setAttr(reinterpret_cast<void*>(itemView), "set item texture seed", static_cast<float>(cfg.seed));
    }
    if (g_updateSkin) {
        g_updateSkin(reinterpret_cast<void*>(weapon), true);
    }
    // Composite material update re-applies the texture on the viewmodel.
    if (g_updateComp) {
        g_updateComp(reinterpret_cast<void*>(weapon + 0x608), true);
    }
    if (g_updateCompSet) {
        g_updateCompSet(reinterpret_cast<void*>(weapon), false);
    }
}

static void ApplyViewmodelMask(uintptr_t client, uintptr_t pawn, int meshMask) {
    // The first-person viewmodel (hud arms + weapon) is what the user sees.
    // Its scene node children carry the mesh group masks; set them so only the
    // painted group renders (legacy=2, normal=1) instead of all groups.
    uint32_t armsHandle = *reinterpret_cast<uint32_t*>(pawn + OFF_M_HHUDMODELARMS);
    uintptr_t arms = ResolveEntity(client, armsHandle);
    if (!arms) return;
    uintptr_t sceneNode = *reinterpret_cast<uintptr_t*>(arms + OFF_M_PGAMESCENENODE);
    if (!sceneNode) return;
    uintptr_t child = *reinterpret_cast<uintptr_t*>(sceneNode + 64);  // m_pChild
    int guard = 0;
    while (child && guard++ < 16) {
        if (g_setMask)
            g_setMask(reinterpret_cast<void*>(child), static_cast<uint64_t>(meshMask));
        else
            *reinterpret_cast<uint64_t*>(child + OFF_M_MODELSTATE + OFF_M_MESHGROUPMASK) = static_cast<uint64_t>(meshMask);
        child = *reinterpret_cast<uintptr_t*>(child + 72);  // m_pNextSibling
    }
}

static uint32_t MakeSubclassToken(uint16_t defIndex) {
    // Murmur2 lowercase of the decimal def index (matches CS2's subclass id).
    char buf[8];
    int n = snprintf(buf, sizeof(buf), "%u", static_cast<unsigned>(defIndex));
    if (n <= 0 || n >= static_cast<int>(sizeof(buf))) return 0;
    const uint32_t m = 0x5bd1e995;
    const uint32_t r = 24;
    uint32_t h = 0x31415926u ^ static_cast<uint32_t>(n);
    int i = 0;
    auto lower = [](char c) { return (c >= 'A' && c <= 'Z') ? char(c + 32) : c; };
    while (n >= 4) {
        uint32_t k = static_cast<uint32_t>(static_cast<unsigned char>(lower(buf[i]))) |
            (static_cast<uint32_t>(static_cast<unsigned char>(lower(buf[i + 1]))) << 8) |
            (static_cast<uint32_t>(static_cast<unsigned char>(lower(buf[i + 2]))) << 16) |
            (static_cast<uint32_t>(static_cast<unsigned char>(lower(buf[i + 3]))) << 24);
        k *= m; k ^= k >> r; k *= m;
        h *= m; h ^= k;
        i += 4; n -= 4;
    }
    switch (n) {
    case 3: h ^= static_cast<uint32_t>(static_cast<unsigned char>(lower(buf[i + 2]))) << 16; [[fallthrough]];
    case 2: h ^= static_cast<uint32_t>(static_cast<unsigned char>(lower(buf[i + 1]))) << 8; [[fallthrough]];
    case 1: h ^= static_cast<unsigned char>(lower(buf[i])); h *= m;
    }
    h ^= h >> 13; h *= m; h ^= h >> 15;
    return h;
}

static void Loop() {
    uintptr_t client = reinterpret_cast<uintptr_t>(GetModuleHandleA("client.dll"));
    if (!client) {
        DllLog("loop: client.dll not found, aborting");
        return;
    }
    DllLog("loop: client.dll base=%p", (void*)client);
    ResolveFunctions();
    DllLog("loop: entering main loop, skins=%d", (int)g_skins.size());
    while (true) {
        ReadConfig();
        uintptr_t pawn = *reinterpret_cast<uintptr_t*>(client + OFF_DW_LOCAL_PLAYER_PAWN);
        if (!pawn) {
            Sleep(250);
            continue;
        }
        uintptr_t ws = *reinterpret_cast<uintptr_t*>(pawn + OFF_M_PWEAPONSERVICES);
        if (!ws) {
            Sleep(100);
            continue;
        }
        uint32_t handle = *reinterpret_cast<uint32_t*>(ws + OFF_M_HACTIVEWEAPON);
        uintptr_t weapon = ResolveEntity(client, handle);
        if (!weapon) {
            Sleep(100);
            continue;
        }
        uintptr_t itemView = weapon + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM;
        uint16_t def = *reinterpret_cast<uint16_t*>(itemView + OFF_M_ITEMDEFINDEX);
        const bool isKnife = (def == 42 || def == 59 || (def >= 500 && def <= 526));
        std::lock_guard<std::mutex> lock(g_mtx);
        bool applied = false;
        if (isKnife) {
            // Knives: apply the most recently configured knife (last knife entry
            // in the file), model-swapping as needed. This lets the GUI switch
            // the held knife's model/skin immediately.
            const SkinCfg* pick = nullptr;
            uint16_t pickDef = 0;
            for (const auto& [d, cfg] : g_skins) {
                if (d >= 500 && d <= 526) { pick = &cfg; pickDef = d; }
            }
            if (pick) {
                DllLog("apply: def=%u paint=%d seed=%d wear=%.3f mesh=%d model=%s weapon=%p",
                    (unsigned)def, pick->paint, pick->seed, pick->wear, pick->meshMask, pick->model.c_str(), (void*)weapon);
                ApplySkin(weapon, *pick, pickDef);
                ApplyViewmodelMask(client, pawn, pick->meshMask);
                if (!pick->model.empty() && g_setModel) {
                    g_setModel(reinterpret_cast<void*>(weapon), pick->model.c_str());
                    // Subclass id + refresh drives the knife's animation class
                    // (e.g. butterfly flip instead of default knife slash).
                    *reinterpret_cast<uint32_t*>(weapon + 896) = MakeSubclassToken(pickDef);  // m_nSubclassID
                    if (g_updateSubclass) g_updateSubclass(reinterpret_cast<void*>(weapon));
                    if (g_updateWeaponVm) g_updateWeaponVm(reinterpret_cast<void*>(weapon));
                }
                applied = true;
            }
        } else {
            for (const auto& [d, cfg] : g_skins) {
                if (d != def) continue;
                DllLog("apply: def=%u paint=%d seed=%d wear=%.3f mesh=%d model=%s weapon=%p",
                    (unsigned)def, cfg.paint, cfg.seed, cfg.wear, cfg.meshMask, cfg.model.c_str(), (void*)weapon);
                ApplySkin(weapon, cfg, def);
                ApplyViewmodelMask(client, pawn, cfg.meshMask);
                applied = true;
                break;
            }
        }
        if (!applied) {
            DllLog("nomatch: def=%u isKnife=%d skins=%d", (unsigned)def, (int)isKnife, (int)g_skins.size());
        }
        Sleep(100);
    }
}

static DWORD WINAPI LoopThread(LPVOID) {
    Loop();
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        DllLog("DllMain: attach, module=%p", (void*)hModule);
        // Do NOT use std::thread here: constructing a CRT thread during
        // DLL_PROCESS_ATTACH can deadlock on the loader lock (the new thread's
        // CRT startup re-acquires it while LoadLibraryA still holds it). A raw
        // CreateThread returns immediately and lets Loop run after DllMain
        // returns and the lock is released.
        CreateThread(nullptr, 0, LoopThread, nullptr, 0, nullptr);
    } else if (reason == DLL_PROCESS_DETACH) {
        DllLog("DllMain: detach, module=%p", (void*)hModule);
    }
    return TRUE;
}
