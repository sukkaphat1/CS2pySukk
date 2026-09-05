// skinchanger.cpp - internal CS2 skin changer (manually-mapped DLL).
//
// Built CRT-free (/NODEFAULTLIB, /ENTRY:DllMain) so it can be manually mapped
// into cs2.exe without depending on the C runtime's DllMain startup. It only
// imports kernel32 functions. It reads %USERPROFILE%\cs2py_skin.txt (lines:
// "defIndex paintKit seed wear meshMask model") and applies the configured skin
// to the local player's active weapon in-process.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#include <stdint.h>
#include <stdarg.h>

// Satisfies the compiler's floating-point marker when linking without the CRT.
extern "C" int _fltused = 0;

// Minimal CRT substitutes for the few libc helpers the compiler may still emit
// (struct copies / zeroing) in a CRT-free build. Implemented here so we never
// link the C runtime. On x64 the linker matches these by symbol name only.
#pragma function(memset, memcpy, memmove)
extern "C" void* __cdecl memset(void* dst, int c, SIZE_T n) {
    unsigned char* d = (unsigned char*)dst;
    for (SIZE_T i = 0; i < n; i++) d[i] = (unsigned char)c;
    return dst;
}

extern "C" void* __cdecl memcpy(void* dst, const void* src, SIZE_T n) {
    unsigned char* d = (unsigned char*)dst;
    const unsigned char* s = (const unsigned char*)src;
    for (SIZE_T i = 0; i < n; i++) d[i] = s[i];
    return dst;
}

extern "C" void* __cdecl memmove(void* dst, const void* src, SIZE_T n) {
    unsigned char* d = (unsigned char*)dst;
    const unsigned char* s = (const unsigned char*)src;
    if (d < s) { for (SIZE_T i = 0; i < n; i++) d[i] = s[i]; }
    else { for (SIZE_T i = n; i > 0; i--) d[i - 1] = s[i - 1]; }
    return dst;
}

// Offsets (current cs2-dumper dump)
static const uintptr_t OFF_DW_GAMERULES         = 37510440;
static const uintptr_t OFF_DW_LOCAL_PLAYER_PAWN = 37511784;
static const uintptr_t OFF_DW_ENTITY_LIST      = 39260704;
static const uintptr_t OFF_M_PWEAPONSERVICES   = 4616;
static const uintptr_t OFF_M_HMYWEARABLES      = 4480;
static const uintptr_t OFF_M_HACTIVEWEAPON     = 96;
static const uintptr_t OFF_M_ATTRIBUTEMANAGER  = 4520;
static const uintptr_t OFF_M_ITEM              = 80;
static const uintptr_t OFF_M_ITEMDEFINDEX      = 442;
static const uintptr_t OFF_M_ITEMID            = 456;
static const uintptr_t OFF_M_ITEMIDHIGH        = 464;
static const uintptr_t OFF_M_ITEMIDLOW         = 468;
static const uintptr_t OFF_M_ACCOUNTID         = 472;
static const uintptr_t OFF_M_BDISALLOWSOC      = 489;
static const uintptr_t OFF_M_BINITIALIZED      = 488;
static const uintptr_t OFF_M_BRESTORECUSTOM    = 440;
static const uintptr_t OFF_M_OWNERXUIDLOW      = 5752;
static const uintptr_t OFF_M_OWNERXUIDHIGH     = 5756;
static const uintptr_t OFF_M_FALLBACKPAINTKIT  = 5760;
static const uintptr_t OFF_M_FALLBACKSEED      = 5764;
static const uintptr_t OFF_M_FALLBACKWEAR      = 5768;
static const uintptr_t OFF_M_FALLBACKSTATTRAK  = 5772;
static const uintptr_t OFF_M_PGAMESCENENODE    = 816;
static const uintptr_t OFF_M_MODELSTATE        = 320;
static const uintptr_t OFF_M_MESHGROUPMASK     = 520;
static const uintptr_t OFF_M_HHUDMODELARMS     = 7044;

// ---- tiny string/format helpers (no CRT) --------------------------------

static void copy_str(char* dst, const char* src, int cap) {
    int i = 0;
    while (src[i] && i < cap - 1) { dst[i] = src[i]; i++; }
    dst[i] = 0;
}

static void build_path(char* out, int cap, const char* dir, const char* file) {
    int i = 0;
    while (dir[i] && i < cap - 1) { out[i] = dir[i]; i++; }
    if (i < cap - 1) out[i++] = '\\';
    int j = 0;
    while (file[j] && i < cap - 1) { out[i++] = file[j++]; }
    out[i] = 0;
}

static char lower_c(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

static int str_eq(const char* a, const char* b) {
    while (*a && *b) {
        if (*a != *b) return 0;
        a++; b++;
    }
    return *a == *b;
}

static int str_contains(const char* haystack, const char* needle) {
    if (!haystack || !needle) return 0;
    if (!*needle) return 1;
    while (*haystack) {
        const char* h = haystack;
        const char* n = needle;
        while (*h && *n && *h == *n) { h++; n++; }
        if (!*n) return 1;
        haystack++;
    }
    return 0;
}

// Knife item defs are 500-526 EXCEPT 5027-5035, which are gloves (they overlap
// the knife range in items_game.txt). Gloves are a separate wearables entity.
static int is_knife_def(uint16_t def) {
    return def == 42 || def == 59 ||
        (def >= 500 && def <= 526 && !(def >= 5027 && def <= 5035));
}

static int is_glove_def(uint16_t def) {
    return (def >= 5027 && def <= 5035) || def == 4725;
}

// Reject null/low/high pointers and unmapped pages. During map teardown the
// game frees + unmaps entities while our loop still holds their old addresses;
// dereferencing those is exactly what access-violates cs2 on exit/match end.
// IsBadReadPtr probes safely (SEH) so this never faults on its own.
static int safe_ptr(uintptr_t p) {
    if (p < 0x10000 || p > 0x7FFFFFFFFFFFull) return 0;
    return !IsBadReadPtr((const void*)p, 8);
}

// Writes the decimal representation of v into out, returns digit count.
static int u32toa(char* out, uint32_t v) {
    char tmp[12];
    int n = 0;
    do { tmp[n++] = (char)('0' + (v % 10)); v /= 10; } while (v);
    for (int i = 0; i < n; i++) out[i] = tmp[n - 1 - i];
    return n;
}

static void log_append(char** p, const char* s) {
    while (*s) { *(*p)++ = *s++; }
}

static void log_u32(char** p, uint32_t v) {
    char tmp[16];
    int n = 0;
    do { tmp[n++] = (char)('0' + (v % 10)); v /= 10; } while (v);
    while (n--) *(*p)++ = tmp[n];
}

static void log_u32_pad(char** p, uint32_t v, int width) {
    char tmp[16];
    int n = 0;
    do { tmp[n++] = (char)('0' + (v % 10)); v /= 10; } while (v);
    while (n < width) tmp[n++] = '0';
    while (n--) *(*p)++ = tmp[n];
}

static void log_i32(char** p, int32_t v) {
    if (v < 0) { *(*p)++ = '-'; log_u32(p, (uint32_t)(-(int64_t)v)); }
    else log_u32(p, (uint32_t)v);
}

static void log_hex64(char** p, uint64_t v) {
    char tmp[16];
    int n = 0;
    do {
        int d = (int)(v & 0xF);
        tmp[n++] = (char)(d < 10 ? '0' + d : 'a' + d - 10);
        v >>= 4;
    } while (v);
    while (n--) *(*p)++ = tmp[n];
}

static void log_float3(char** p, float f) {
    int whole = (int)f;
    int frac = (int)((f - (float)whole) * 1000.0f + 0.5f);
    if (frac < 0) frac = 0;
    if (frac >= 1000) { whole += 1; frac = 0; }
    log_i32(p, (int32_t)whole);
    *(*p)++ = '.';
    char tmp[3];
    tmp[2] = (char)('0' + (frac % 10)); frac /= 10;
    tmp[1] = (char)('0' + (frac % 10)); frac /= 10;
    tmp[0] = (char)('0' + (frac % 10));
    *(*p)++ = tmp[0]; *(*p)++ = tmp[1]; *(*p)++ = tmp[2];
}

static char g_configPath[MAX_PATH] = { 0 };
static char g_logPath[MAX_PATH] = { 0 };

static void ResolveUserPaths() {
    if (g_configPath[0]) return;  // already resolved
    char up[MAX_PATH];
    up[0] = 0;
    DWORD n = GetEnvironmentVariableA("USERPROFILE", up, MAX_PATH);
    if (!n || n >= MAX_PATH) copy_str(up, "C:\\Users\\Public", MAX_PATH);
    build_path(g_configPath, MAX_PATH, up, "cs2py_skin.txt");
    build_path(g_logPath, MAX_PATH, up, "cs2py_dll.log");
}

static void DllLog(const char* fmt, ...) {
    char line[1024];
    char* p = line;
    SYSTEMTIME st;
    GetLocalTime(&st);
    log_u32_pad(&p, st.wHour, 2); *p++ = ':';
    log_u32_pad(&p, st.wMinute, 2); *p++ = ':';
    log_u32_pad(&p, st.wSecond, 2); *p++ = '.';
    log_u32_pad(&p, st.wMilliseconds, 3); *p++ = ' ';

    va_list ap;
    va_start(ap, fmt);
    while (*fmt) {
        if (*fmt != '%') { *p++ = *fmt++; continue; }
        fmt++;
        if (*fmt == 's') { const char* s = va_arg(ap, const char*); log_append(&p, s ? s : "(null)"); }
        else if (*fmt == 'p') { log_hex64(&p, (uint64_t)(uintptr_t)va_arg(ap, void*)); }
        else if (*fmt == 'u') { log_u32(&p, (uint32_t)va_arg(ap, unsigned int)); }
        else if (*fmt == 'd') { log_i32(&p, (int32_t)va_arg(ap, int)); }
        else if (*fmt == '.' && fmt[1] == '3' && fmt[2] == 'f') { fmt += 2; log_float3(&p, (float)va_arg(ap, double)); }
        fmt++;
    }
    va_end(ap);
    *p++ = '\n';
    *p = 0;

    ResolveUserPaths();
    HANDLE f = CreateFileA(g_logPath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f != INVALID_HANDLE_VALUE) {
        DWORD written = 0;
        WriteFile(f, line, (DWORD)(p - line), &written, NULL);
        CloseHandle(f);
    }
}

// ---- config storage (no STL) -------------------------------------------

typedef struct SkinCfg {
    int paint;
    int seed;
    float wear;
    int meshMask;
    char model[320];
} SkinCfg;

typedef struct SkinEntry {
    uint16_t def;
    SkinCfg cfg;
} SkinEntry;

static SkinEntry g_skins[64];
static int g_skin_count = 0;
static SRWLOCK g_lock = SRWLOCK_INIT;
static char g_filebuf[65536];

// ---- function pointers --------------------------------------------------

typedef void(__fastcall* SetAttrFn)(void*, const char*, float);
typedef void(__fastcall* UpdateSkinFn)(void*, bool);
typedef void(__fastcall* UpdateCompFn)(void*, bool);
typedef void(__fastcall* UpdateCompSetFn)(void*, bool);
typedef void(__fastcall* SetMaskFn)(void*, uint64_t);
typedef void(__fastcall* SetModelFn)(void*, const char*);
typedef void(__fastcall* UpdateSubclassFn)(void*);
typedef void(__fastcall* UpdateWeaponVmFn)(void*);

static SetAttrFn g_setAttr = 0;
static UpdateSkinFn g_updateSkin = 0;
static UpdateCompFn g_updateComp = 0;
static UpdateCompSetFn g_updateCompSet = 0;
static SetMaskFn g_setMask = 0;
static SetModelFn g_setModel = 0;
static UpdateSubclassFn g_updateSubclass = 0;
static UpdateWeaponVmFn g_updateWeaponVm = 0;

// ---- pattern scanning ---------------------------------------------------

static int hexval(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return 0;
}

static uintptr_t PatternScan(const char* module, const char* pattern) {
    HMODULE mod = GetModuleHandleA(module);
    if (!mod) return 0;
    uint8_t* base = (uint8_t*)mod;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)mod;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    uintptr_t size = nt->OptionalHeader.SizeOfImage;

    uint8_t pat[64];
    uint8_t mask[64];
    int n = 0;
    const char* p = pattern;
    while (*p) {
        while (*p == ' ') p++;
        if (!*p) break;
        if (p[0] == '?' && (p[1] == 0 || p[1] == ' ')) {
            pat[n] = 0; mask[n] = 0; n++;
            p++;
        } else {
            pat[n] = (uint8_t)((hexval(p[0]) << 4) | hexval(p[1]));
            mask[n] = 1; n++;
            p += 2;
        }
        if (n >= 63) break;
    }
    if (n == 0) return 0;

    for (uintptr_t i = 0; i + n <= size; i++) {
        int ok = 1;
        for (int j = 0; j < n; j++) {
            if (mask[j] && base[i + j] != pat[j]) { ok = 0; break; }
        }
        if (ok) return (uintptr_t)(base + i);
    }
    return 0;
}

static uintptr_t ScanCall(const char* pattern) {
    uintptr_t call = PatternScan("client.dll", pattern);
    if (!call) return 0;
    int32_t rel = *(int32_t*)(call + 1);
    return call + 5 + rel;
}

static void ResolveFunctions() {
    if (g_setAttr && g_updateSkin && g_updateComp && g_updateCompSet) return;
    // SetAttributeValueByName: CALL instruction; resolve rel32.
    uintptr_t call = PatternScan("client.dll", "E8 ? ? ? ? 66 41 0F 6E D4");
    if (call) {
        int32_t rel = *(int32_t*)(call + 1);
        g_setAttr = (SetAttrFn)(call + 5 + rel);
    }
    // C_CSWeaponBase::UpdateSkin: function prologue.
    g_updateSkin = (UpdateSkinFn)PatternScan("client.dll",
        "48 89 5C 24 08 57 48 83 EC 20 8B DA 48 8B F9 E8 ? ? ? ? F6 C3 01 74 0A");
    // UpdateCompositeMaterial: prefer the CALL pattern, then the direct prologue.
    g_updateComp = (UpdateCompFn)ScanCall("E8 ? ? ? ? 48 8D 8B ? ? ? ? 48 89 BC 24");
    if (!g_updateComp)
        g_updateComp = (UpdateCompFn)PatternScan("client.dll",
            "48 89 5C 24 10 48 89 6C 24 18 48 89 74 24 20 57 41 56 41 57 48 83 EC 20 44 0F B6 F2");
    // UpdateCompositeMaterialSet.
    g_updateCompSet = (UpdateCompSetFn)PatternScan("client.dll",
        "40 55 53 41 57 48 8D AC 24 00 FE ? ?");
    // SetMeshGroupMask (game function; does the mesh refresh we need).
    g_setMask = (SetMaskFn)PatternScan("client.dll",
        "48 89 5C 24 ? 48 89 74 24 ? 57 48 83 EC ? 48 8D 99 ? ? ? ? 48 8B 71");
    // SetModel (for the knife model swap).
    g_setModel = (SetModelFn)PatternScan("client.dll",
        "40 53 48 83 EC ? 48 8B D9 4C 8B C2 48 8B 0D ? ? ? ? 48 8D 54 24 40");
    // UpdateSubclass + UpdateWeaponViewModel (knife animation class).
    g_updateSubclass = (UpdateSubclassFn)PatternScan("client.dll",
        "4C 8B DC 53 48 81 EC ? ? ? ? 48 8B 41");
    g_updateWeaponVm = (UpdateWeaponVmFn)PatternScan("client.dll",
        "40 53 48 83 EC 20 48 8B D9 E8 ? ? ? ? 48 83 BB 88 03 00 00 00");

    DllLog("resolve: setAttr=%p updateSkin=%p updateComp=%p updateCompSet=%p setMask=%p setModel=%p updateSubclass=%p updateWeaponVm=%p",
        (void*)g_setAttr, (void*)g_updateSkin, (void*)g_updateComp, (void*)g_updateCompSet,
        (void*)g_setMask, (void*)g_setModel, (void*)g_updateSubclass, (void*)g_updateWeaponVm);
}

// ---- config parsing (no iostream) --------------------------------------

static int is_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

static void skip_ws(const char** s, const char* end) {
    while (*s < end && is_space(**s)) (*s)++;
}

static int parse_i32(const char** s, const char* end, int* out) {
    skip_ws(s, end);
    if (*s >= end) return 0;
    int sign = 1;
    if (**s == '-') { sign = -1; (*s)++; }
    if (*s >= end || **s < '0' || **s > '9') return 0;
    long v = 0;
    while (*s < end && **s >= '0' && **s <= '9') {
        v = v * 10 + (**s - '0');
        (*s)++;
        if (v > 0x7FFFFFFF) v = 0x7FFFFFFF;
    }
    *out = (int)(sign * v);
    return 1;
}

static int parse_float(const char** s, const char* end, float* out) {
    skip_ws(s, end);
    if (*s >= end) return 0;
    int sign = 1;
    if (**s == '-') { sign = -1; (*s)++; }
    if (*s >= end || (**s < '0' || **s > '9')) return 0;
    double whole = 0.0;
    while (*s < end && **s >= '0' && **s <= '9') { whole = whole * 10.0 + (**s - '0'); (*s)++; }
    double frac = 0.0;
    if (*s < end && **s == '.') {
        (*s)++;
        double place = 0.1;
        while (*s < end && **s >= '0' && **s <= '9') {
            frac += (**s - '0') * place;
            place *= 0.1;
            (*s)++;
        }
    }
    *out = (float)(sign * (whole + frac));
    return 1;
}

static void parse_token(const char** s, const char* end, char* out, int cap) {
    skip_ws(s, end);
    int i = 0;
    while (*s < end && !is_space(**s) && i < cap - 1) { out[i++] = **s; (*s)++; }
    out[i] = 0;
}

static void ReadConfig() {
    ResolveUserPaths();
    HANDLE f = CreateFileA(g_configPath, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return;
    DWORD size = GetFileSize(f, NULL);
    if (size == 0) { g_skin_count = 0; CloseHandle(f); return; }
    if (size >= sizeof(g_filebuf)) { CloseHandle(f); return; }
    DWORD rd = 0;
    if (!ReadFile(f, g_filebuf, size, &rd, NULL)) { CloseHandle(f); return; }
    CloseHandle(f);

    AcquireSRWLockExclusive(&g_lock);
    g_skin_count = 0;
    const char* s = g_filebuf;
    const char* end = g_filebuf + rd;
    while (s < end) {
        int def = 0, paint = 0, seed = 0, mesh = 1;
        float wear = 0.0f;
        char model[320];
        model[0] = 0;
        if (!parse_i32(&s, end, &def)) break;
        if (!parse_i32(&s, end, &paint)) break;
        if (!parse_i32(&s, end, &seed)) break;
        if (!parse_float(&s, end, &wear)) break;
        if (!parse_i32(&s, end, &mesh)) break;
        parse_token(&s, end, model, sizeof(model));
        if (model[0] == '-' && model[1] == 0) model[0] = 0;
        if (g_skin_count < 64) {
            g_skins[g_skin_count].def = (uint16_t)def;
            g_skins[g_skin_count].cfg.paint = paint;
            g_skins[g_skin_count].cfg.seed = seed;
            g_skins[g_skin_count].cfg.wear = wear;
            g_skins[g_skin_count].cfg.meshMask = mesh;
            copy_str(g_skins[g_skin_count].cfg.model, model, (int)sizeof(model));
            g_skin_count++;
        }
    }
    ReleaseSRWLockExclusive(&g_lock);
}

// ---- entity resolution --------------------------------------------------

static uintptr_t ResolveEntity(uintptr_t client, uint32_t handle) {
    if (!handle || handle == 0xFFFFFFFFu) return 0;
    uintptr_t entityList = *(uintptr_t*)(client + OFF_DW_ENTITY_LIST);
    if (!entityList || !safe_ptr(entityList)) return 0;
    uintptr_t listEntry = *(uintptr_t*)(entityList + 0x8 * ((handle & 0x7FFF) >> 9) + 0x10);
    if (!listEntry || !safe_ptr(listEntry)) return 0;
    return *(uintptr_t*)(listEntry + 0x70 * (handle & 0x1FF));
}

// ---- skin application ---------------------------------------------------

static void PokeFields(uintptr_t weapon, const SkinCfg* cfg, uint16_t defIndex) {
    // Cheap direct memory writes only (no game function calls). Safe to run
    // every tick to resist the game resetting the fallback fields.
    uintptr_t itemView = weapon + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM;
    uint32_t accountId = *(uint32_t*)(weapon + OFF_M_OWNERXUIDLOW);
    if (!accountId) accountId = 1;

    *(uint8_t*)(itemView + OFF_M_BDISALLOWSOC) = 1;
    *(uint8_t*)(itemView + OFF_M_BRESTORECUSTOM) = 1;
    *(uint8_t*)(itemView + OFF_M_BINITIALIZED) = 1;
    *(uint32_t*)(itemView + OFF_M_ACCOUNTID) = accountId;
    *(uint16_t*)(itemView + OFF_M_ITEMDEFINDEX) = defIndex;
    *(uint32_t*)(itemView + OFF_M_ITEMIDHIGH) = 0xFFFFFFFFu;
    *(uint32_t*)(itemView + OFF_M_ITEMIDLOW) = 0;
    *(uint64_t*)(itemView + OFF_M_ITEMID) = 0xFFFFFFFF00000000ull;

    *(uint32_t*)(weapon + OFF_M_OWNERXUIDLOW) = accountId;
    *(uint32_t*)(weapon + OFF_M_OWNERXUIDHIGH) = 0;
    *(int32_t*)(weapon + OFF_M_FALLBACKPAINTKIT) = cfg->paint;
    *(int32_t*)(weapon + OFF_M_FALLBACKSEED) = cfg->seed;
    *(float*)(weapon + OFF_M_FALLBACKWEAR) = cfg->wear;
    *(int32_t*)(weapon + OFF_M_FALLBACKSTATTRAK) = -1;
}

static void ApplySkin(uintptr_t weapon, const SkinCfg* cfg, uint16_t defIndex) {
    uintptr_t itemView = weapon + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM;
    PokeFields(weapon, cfg, defIndex);

    // Mesh group mask via the game's own setter (does the mesh refresh).
    if (g_setMask) {
        uintptr_t wSceneNode = *(uintptr_t*)(weapon + OFF_M_PGAMESCENENODE);
        if (wSceneNode && safe_ptr(wSceneNode)) g_setMask((void*)wSceneNode, (uint64_t)cfg->meshMask);
    }

    if (g_setAttr) {
        g_setAttr((void*)itemView, "set item texture prefab", (float)cfg->paint);
        g_setAttr((void*)itemView, "set item texture wear", cfg->wear);
        g_setAttr((void*)itemView, "set item texture seed", (float)cfg->seed);
    }
    if (g_updateSkin) {
        g_updateSkin((void*)weapon, true);
    }
    // Composite material update re-applies the texture on the viewmodel.
    if (g_updateComp) {
        g_updateComp((void*)(weapon + 0x608), true);
    }
    if (g_updateCompSet) {
        g_updateCompSet((void*)weapon, false);
    }
}

static void ApplyViewmodelMask(uintptr_t client, uintptr_t pawn, int meshMask) {
    // The first-person viewmodel (hud arms + weapon) is what the user sees.
    // Its scene node children carry the mesh group masks; set them so only the
    // painted group renders (legacy=2, normal=1) instead of all groups.
    uint32_t armsHandle = *(uint32_t*)(pawn + OFF_M_HHUDMODELARMS);
    uintptr_t arms = ResolveEntity(client, armsHandle);
    if (!arms) return;
    uintptr_t sceneNode = *(uintptr_t*)(arms + OFF_M_PGAMESCENENODE);
    if (!sceneNode) return;
    uintptr_t child = *(uintptr_t*)(sceneNode + 64);  // m_pChild
    int guard = 0;
    while (child && guard++ < 16) {
        if (!safe_ptr(child)) break;
        if (g_setMask)
            g_setMask((void*)child, (uint64_t)meshMask);
        else
            *(uint64_t*)(child + OFF_M_MODELSTATE + OFF_M_MESHGROUPMASK) = (uint64_t)meshMask;
        child = *(uintptr_t*)(child + 72);  // m_pNextSibling
    }
}

// Set the model on the first-person KNIFE viewmodel entity (the HUD arms
// scene-node child whose model name contains "knife"). A knife model swap must
// update this too, otherwise UpdateWeaponViewModel finds an inconsistent
// viewmodel and corrupts it. We deliberately skip the gun viewmodels so they
// keep their own model after switching back to a gun.
static void SetKnifeHudViewModel(uintptr_t client, uintptr_t pawn, const char* model) {
    if (!model || !model[0] || !g_setModel) return;
    uint32_t armsHandle = *(uint32_t*)(pawn + OFF_M_HHUDMODELARMS);
    uintptr_t arms = ResolveEntity(client, armsHandle);
    if (!arms || !safe_ptr(arms)) return;
    uintptr_t sceneNode = *(uintptr_t*)(arms + OFF_M_PGAMESCENENODE);
    if (!sceneNode || !safe_ptr(sceneNode)) return;
    uintptr_t child = *(uintptr_t*)(sceneNode + 64);  // m_pChild
    int guard = 0;
    while (child && guard++ < 16) {
        if (!safe_ptr(child)) break;
        // CModelState m_ModelName (CUtlString) at sceneNode + m_modelState(320)
        // + m_ModelName(168); its data pointer is the model path.
        const char* mn = (const char*)*(uintptr_t*)(child + OFF_M_MODELSTATE + 168);
        if (mn && safe_ptr((uintptr_t)mn) && str_contains(mn, "knife")) {
            uintptr_t owner = *(uintptr_t*)(child + 48);  // m_pOwner -> C_BaseEntity
            if (owner && safe_ptr(owner)) {
                g_setModel((void*)owner, model);
            }
        }
        child = *(uintptr_t*)(child + 72);  // m_pNextSibling
    }
}

static uint32_t MakeSubclassToken(uint16_t defIndex) {
    // Murmur2 lowercase of the decimal def index (matches CS2's subclass id).
    char buf[8];
    int n = u32toa(buf, (uint32_t)defIndex);
    if (n <= 0 || n >= 8) return 0;
    const uint32_t m = 0x5bd1e995u;
    const uint32_t r = 24;
    uint32_t h = 0x31415926u ^ (uint32_t)n;
    int i = 0;
    while (n >= 4) {
        uint32_t k = (uint32_t)(uint8_t)lower_c(buf[i]) |
            ((uint32_t)(uint8_t)lower_c(buf[i + 1]) << 8) |
            ((uint32_t)(uint8_t)lower_c(buf[i + 2]) << 16) |
            ((uint32_t)(uint8_t)lower_c(buf[i + 3]) << 24);
        k *= m; k ^= k >> r; k *= m;
        h *= m; h ^= k;
        i += 4; n -= 4;
    }
    switch (n) {
    case 3:
        h ^= (uint32_t)(uint8_t)lower_c(buf[i + 2]) << 16;
        h ^= (uint32_t)(uint8_t)lower_c(buf[i + 1]) << 8;
        h ^= (uint8_t)lower_c(buf[i]);
        h *= m;
        break;
    case 2:
        h ^= (uint32_t)(uint8_t)lower_c(buf[i + 1]) << 8;
        h ^= (uint8_t)lower_c(buf[i]);
        h *= m;
        break;
    case 1:
        h ^= (uint8_t)lower_c(buf[i]);
        h *= m;
        break;
    }
    h ^= h >> 13; h *= m; h ^= h >> 15;
    return h;
}

// ---- glove application --------------------------------------------------

static void ApplyGloveSkin(uintptr_t entity, const SkinCfg* cfg, uint16_t defIndex) {
    PokeFields(entity, cfg, defIndex);
    uintptr_t itemView = entity + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM;
    if (g_setAttr) {
        g_setAttr((void*)itemView, "set item texture prefab", (float)cfg->paint);
        g_setAttr((void*)itemView, "set item texture wear", cfg->wear);
        g_setAttr((void*)itemView, "set item texture seed", (float)cfg->seed);
    }
    // NOTE: no UpdateSkin/UpdateCompositeMaterial here. Those are resolved to
    // C_CSWeaponBase methods and would touch weapon-specific fields on a
    // C_EconWearable (glove). The field + attribute writes above are enough.
}

// Find the glove wearable (C_EconWearable) via m_hMyWearables and apply the
// configured glove skin, model-swapping when the glove type changes.
static void ApplyGloves(uintptr_t client, uintptr_t pawn) {
    static uintptr_t lastEntity = 0;
    static uint16_t lastDef = 0;
    static int lastPaint = -1;
    static int lastSeed = -1;
    static int lastMesh = -1;
    static float lastWear = -1.0f;
    static char lastModel[320];
    static int haveLast = 0;
    static int dbgDone = 0;
    static uint64_t lastPokeTick = 0;

    const SkinCfg* gc = 0;
    uint16_t gd = 0;
    for (int i = 0; i < g_skin_count; i++) {
        if (is_glove_def(g_skins[i].def)) {
            gc = &g_skins[i].cfg;
            gd = g_skins[i].def;
        }
    }
    if (!gc) { haveLast = 0; return; }

    uintptr_t wearables = *(uintptr_t*)(pawn + OFF_M_HMYWEARABLES);
    int32_t count = (wearables && safe_ptr(wearables)) ? *(int32_t*)(pawn + OFF_M_HMYWEARABLES + 8) : 0;

    // One-time diagnostic: show the raw m_hMyWearables state so we can confirm
    // the offset + CUtlVector layout are right on this build.
    if (!dbgDone) {
        dbgDone = 1;
        DllLog("glove: cfg def=%u paint=%d wearables=%p count=%d", (unsigned)gd, gc->paint, (void*)wearables, count);
        for (int i = 0; wearables && i < count && i < 16; i++) {
            uint32_t h = *(uint32_t*)(wearables + (uintptr_t)i * 4);
            uintptr_t e = ResolveEntity(client, h);
            if (e && safe_ptr(e)) {
                uint16_t d = *(uint16_t*)(e + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM + OFF_M_ITEMDEFINDEX);
                DllLog("glove: wearable[%d] handle=0x%X entity=%p def=%u", i, h, (void*)e, (unsigned)d);
            } else {
                DllLog("glove: wearable[%d] handle=0x%X -> no entity", i, h);
            }
        }
        if (!wearables) {
            // m_hMyWearables is empty: scan the whole entity list for any glove
            // entity so we can see where it actually lives on this build.
            uintptr_t entityList = *(uintptr_t*)(client + OFF_DW_ENTITY_LIST);
            if (entityList && safe_ptr(entityList)) {
                int found = 0;
                for (int chunk = 0; chunk < 64 && found < 8; chunk++) {
                    uintptr_t le = *(uintptr_t*)(entityList + 0x8 * chunk + 0x10);
                    if (!le || !safe_ptr(le)) continue;
                    for (int i = 0; i < 512; i++) {
                        uintptr_t e = *(uintptr_t*)(le + 0x70 * i);
                        if (!e || !safe_ptr(e)) continue;
                        uint16_t d = *(uint16_t*)(e + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM + OFF_M_ITEMDEFINDEX);
                        if (is_glove_def(d)) {
                            DllLog("glove: entitylist[%d][%d] def=%u at %p", chunk, i, (unsigned)d, (void*)e);
                            found++;
                        }
                    }
                }
                if (!found) DllLog("glove: entity-list scan found no glove entity");
            }
        }
    }

    if (!wearables || !safe_ptr(wearables)) { haveLast = 0; return; }
    if (count <= 0 || count > 16) { haveLast = 0; return; }

    for (int i = 0; i < count; i++) {
        uint32_t handle = *(uint32_t*)(wearables + (uintptr_t)i * 4);
        uintptr_t entity = ResolveEntity(client, handle);
        if (!entity || !safe_ptr(entity)) continue;
        uintptr_t itemView = entity + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM;
        uint16_t def = *(uint16_t*)(itemView + OFF_M_ITEMDEFINDEX);
        if (!is_glove_def(def)) continue;

        int changed = !haveLast
            || entity != lastEntity
            || gd != lastDef
            || gc->paint != lastPaint
            || gc->seed != lastSeed
            || gc->wear != lastWear
            || gc->meshMask != lastMesh
            || !str_eq(gc->model, lastModel);
        uint64_t now = GetTickCount64();

        if (changed) {
            DllLog("glove: def=%u paint=%d seed=%d wear=%.3f mesh=%d model=%s entity=%p",
                (unsigned)def, gc->paint, gc->seed, gc->wear, gc->meshMask, gc->model, (void*)entity);
            ApplyGloveSkin(entity, gc, gd);
            if (gc->model[0] && g_setModel) {
                g_setModel((void*)entity, gc->model);
            }
            lastEntity = entity;
            lastDef = gd;
            lastPaint = gc->paint;
            lastSeed = gc->seed;
            lastWear = gc->wear;
            lastMesh = gc->meshMask;
            copy_str(lastModel, gc->model, (int)sizeof(lastModel));
            haveLast = 1;
            lastPokeTick = now;
        } else if (now - lastPokeTick >= 2000) {
            PokeFields(entity, gc, gd);
            lastPokeTick = now;
        }
    }
}

#include "skinshare_remote.h"

// ---- main loop ----------------------------------------------------------

static void Loop() {
    uintptr_t client = (uintptr_t)GetModuleHandleA("client.dll");
    if (!client) {
        DllLog("loop: client.dll not found, aborting");
        return;
    }
    DllLog("loop: client.dll base=%p", (void*)client);
    DllLog("skin-share renderer: version=1 SteamID ownership mapping enabled");
    ResolveFunctions();
    DllLog("loop: entering main loop, skins=%d", g_skin_count);

    uintptr_t lastWeapon = 0;
    uint16_t lastDef = 0;
    int lastPaint = -1;
    int lastSeed = -1;
    int lastMesh = -1;
    float lastWear = -1.0f;
    char lastModel[320];
    lastModel[0] = 0;
    int haveLast = 0;
    uint64_t lastPokeTick = 0;

    while (true) {
        ReadConfig();

        // When the game rules are gone we are not in a live match (main menu,
        // map loading/unloading). Touching entity memory during teardown was
        // crashing cs2 (access violation) on "exit to main menu" / match end.
        uintptr_t gameRules = *(uintptr_t*)(client + OFF_DW_GAMERULES);
        if (!gameRules) {
            // Discard pointers from the previous map without dereferencing them.
            memset(g_remoteCache,0,sizeof(g_remoteCache));
            Sleep(250);
            continue;
        }
        uintptr_t pawn = *(uintptr_t*)(client + OFF_DW_LOCAL_PLAYER_PAWN);
        if (!pawn || !safe_ptr(pawn)) {
            Sleep(250);
            continue;
        }

        // --- active weapon / knife ---
        uintptr_t ws = *(uintptr_t*)(pawn + OFF_M_PWEAPONSERVICES);
        if (ws && safe_ptr(ws)) {
            uint32_t handle = *(uint32_t*)(ws + OFF_M_HACTIVEWEAPON);
            uintptr_t weapon = ResolveEntity(client, handle);
            if (weapon && safe_ptr(weapon)) {
                uintptr_t itemView = weapon + OFF_M_ATTRIBUTEMANAGER + OFF_M_ITEM;
                uint16_t def = *(uint16_t*)(itemView + OFF_M_ITEMDEFINDEX);
                const int isKnife = is_knife_def(def);

                AcquireSRWLockShared(&g_lock);
                const SkinCfg* pick = 0;
                uint16_t pickDef = 0;
                if (isKnife) {
                    // Knives: apply the most recently configured knife (last
                    // knife entry in the file), model-swapping as needed.
                    for (int i = 0; i < g_skin_count; i++) {
                        if (is_knife_def(g_skins[i].def)) {
                            pick = &g_skins[i].cfg;
                            pickDef = g_skins[i].def;
                        }
                    }
                } else {
                    for (int i = 0; i < g_skin_count; i++) {
                        if (g_skins[i].def != def) continue;
                        pick = &g_skins[i].cfg;
                        pickDef = def;
                        break;
                    }
                }

                if (!pick) {
                    haveLast = 0;
                } else {
                    // The expensive game functions (SetAttributeValueByName,
                    // UpdateSkin, UpdateCompositeMaterial, SetModel,
                    // UpdateSubclass, UpdateWeaponVm) only run when the target
                    // actually changes. The cheap field writes (PokeFields) also
                    // run only on change now, plus a light 2s re-poke so a rare
                    // game-side reset still gets corrected without hammering the
                    // entity every frame (which caused input hitches).
                    int changed = !haveLast
                        || weapon != lastWeapon
                        || pickDef != lastDef
                        || pick->paint != lastPaint
                        || pick->seed != lastSeed
                        || pick->wear != lastWear
                        || pick->meshMask != lastMesh
                        || !str_eq(pick->model, lastModel);
                    uint64_t now = GetTickCount64();

                    if (changed) {
                        DllLog("apply: def=%u paint=%d seed=%d wear=%.3f mesh=%d model=%s weapon=%p",
                            (unsigned)def, pick->paint, pick->seed, pick->wear, pick->meshMask, pick->model, (void*)weapon);
                        ApplySkin(weapon, pick, pickDef);
                        ApplyViewmodelMask(client, pawn, pick->meshMask);
                        if (isKnife && pick->model[0] && g_setModel) {
                            // Full knife swap: world weapon model + the
                            // first-person viewmodel(s) + subclass id. The
                            // viewmodel model write is what was missing before
                            // and caused UpdateWeaponViewModel to corrupt state.
                            g_setModel((void*)weapon, pick->model);
                            SetKnifeHudViewModel(client, pawn, pick->model);
                            // Subclass id = murmur2(decimal def index) drives
                            // the knife animation class (butterfly flip).
                            *(uint32_t*)(weapon + 896) = MakeSubclassToken(pickDef);  // m_nSubclassID
                            if (g_updateSubclass) g_updateSubclass((void*)weapon);
                            if (g_updateWeaponVm) g_updateWeaponVm((void*)weapon);
                        }
                        lastWeapon = weapon;
                        lastDef = pickDef;
                        lastPaint = pick->paint;
                        lastSeed = pick->seed;
                        lastWear = pick->wear;
                        lastMesh = pick->meshMask;
                        copy_str(lastModel, pick->model, (int)sizeof(lastModel));
                        haveLast = 1;
                        lastPokeTick = now;
                    } else if (now - lastPokeTick >= 2000) {
                        PokeFields(weapon, pick, pickDef);
                        lastPokeTick = now;
                    }
                }
                ReleaseSRWLockShared(&g_lock);
            }
        }

        // --- gloves (wearable entity, independent of the active weapon) ---
        AcquireSRWLockShared(&g_lock);
        ApplyGloves(client, pawn);
        ReleaseSRWLockShared(&g_lock);

        ApplyRemoteSkins(client);

        Sleep(250);
    }
}

static DWORD WINAPI LoopThread(LPVOID) {
    Loop();
    return 0;
}

extern "C" BOOL WINAPI DllMain(HMODULE hModule, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        // NOTE: no DisableThreadLibraryCalls here. Under manual mapping the
        // module is not registered with the loader, and calling that API with
        // an unregistered base walks a stale loader list and faults. It is also
        // unnecessary: an unregistered module never receives thread callbacks.
        DllLog("DllMain: attach, module=%p", (void*)hModule);
        // Raw CreateThread (not std::thread): the new thread starts only after
        // DllMain returns, so the loader lock is never re-entered.
        CreateThread(0, 0, LoopThread, 0, 0, 0);
    } else if (reason == DLL_PROCESS_DETACH) {
        DllLog("DllMain: detach, module=%p", (void*)hModule);
    }
    return TRUE;
}
