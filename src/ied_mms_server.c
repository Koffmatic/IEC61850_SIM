#include "iec61850_model.h"
#include "iec61850_server.h"
#include "hal_thread.h"

#include "red615_static_model.h"
#include "ref615_static_model.h"
#include "reu615_static_model.h"

#include <ctype.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const char* iedName;
    const char* relayType;
    const char* bindAddress;
    int tcpPort;
    const char* valuesPath;
} ProgramOptions;

typedef struct {
    IedModel* model;
    const char* relayType;
} ModelSelection;

typedef struct {
    IedServer server;
    IedModel* model;
    const char* relayType;
    uint64_t lastUpdatedUnixMs;
    size_t warnedTagCount;
    char warnedTags[128][160];
} ServerContext;

typedef bool (*EntryCallback)(ServerContext* context, const char* key, const char* rawValue);

static volatile sig_atomic_t g_running = 1;

static void
print_usage(const char* programName)
{
    printf("Usage: %s --ied-name <name> --type <type> --bind <ip> --port <port> --values <path>\n", programName);
}

static void
handle_signal(int signalId)
{
    (void) signalId;
    g_running = 0;
}

static char*
duplicate_string(const char* value)
{
    size_t length;
    char* copy;

    if (value == NULL)
        return NULL;

    length = strlen(value);
    copy = (char*) malloc(length + 1);
    if (copy == NULL)
        return NULL;

    memcpy(copy, value, length + 1);
    return copy;
}

static bool
parse_int_value(const char* text, int* outValue)
{
    char* endPtr = NULL;
    long parsedValue;

    if ((text == NULL) || (outValue == NULL))
        return false;

    parsedValue = strtol(text, &endPtr, 10);
    if ((endPtr == text) || (*endPtr != '\0'))
        return false;

    *outValue = (int) parsedValue;
    return true;
}

static bool
parse_arguments(int argc, char** argv, ProgramOptions* options)
{
    int argIndex;

    if (options == NULL)
        return false;

    memset(options, 0, sizeof(ProgramOptions));
    options->tcpPort = 102;

    for (argIndex = 1; argIndex < argc; argIndex++) {
        if ((strcmp(argv[argIndex], "--ied-name") == 0) && ((argIndex + 1) < argc)) {
            options->iedName = argv[++argIndex];
        }
        else if ((strcmp(argv[argIndex], "--type") == 0) && ((argIndex + 1) < argc)) {
            options->relayType = argv[++argIndex];
        }
        else if ((strcmp(argv[argIndex], "--bind") == 0) && ((argIndex + 1) < argc)) {
            options->bindAddress = argv[++argIndex];
        }
        else if ((strcmp(argv[argIndex], "--port") == 0) && ((argIndex + 1) < argc)) {
            if (parse_int_value(argv[++argIndex], &options->tcpPort) == false)
                return false;
        }
        else if ((strcmp(argv[argIndex], "--values") == 0) && ((argIndex + 1) < argc)) {
            options->valuesPath = argv[++argIndex];
        }
        else {
            return false;
        }
    }

    return (options->iedName != NULL) && (options->relayType != NULL) &&
           (options->bindAddress != NULL) && (options->valuesPath != NULL);
}

static ModelSelection
select_model(const char* relayType)
{
    ModelSelection selection;

    selection.model = NULL;
    selection.relayType = relayType;

    if (strcmp(relayType, "REF615") == 0)
        selection.model = &REF615MODEL;
    else if (strcmp(relayType, "REU615") == 0)
        selection.model = &REU615MODEL;
    else if (strcmp(relayType, "RED615") == 0)
        selection.model = &RED615MODEL;

    return selection;
}

static char*
read_text_file(const char* path)
{
    FILE* fileHandle;
    long fileSize;
    size_t bytesRead;
    char* buffer;

    if (path == NULL)
        return NULL;

    fileHandle = fopen(path, "rb");
    if (fileHandle == NULL)
        return NULL;

    if (fseek(fileHandle, 0, SEEK_END) != 0) {
        fclose(fileHandle);
        return NULL;
    }

    fileSize = ftell(fileHandle);
    if (fileSize < 0) {
        fclose(fileHandle);
        return NULL;
    }

    if (fseek(fileHandle, 0, SEEK_SET) != 0) {
        fclose(fileHandle);
        return NULL;
    }

    buffer = (char*) malloc((size_t) fileSize + 1u);
    if (buffer == NULL) {
        fclose(fileHandle);
        return NULL;
    }

    bytesRead = fread(buffer, 1, (size_t) fileSize, fileHandle);
    fclose(fileHandle);

    if (bytesRead != (size_t) fileSize) {
        free(buffer);
        return NULL;
    }

    buffer[fileSize] = '\0';
    return buffer;
}

static const char*
skip_whitespace(const char* cursor)
{
    while ((cursor != NULL) && (*cursor != '\0') && isspace((unsigned char) *cursor))
        cursor++;

    return cursor;
}

static const char*
find_matching_brace(const char* cursor)
{
    int depth = 0;

    while ((cursor != NULL) && (*cursor != '\0')) {
        if (*cursor == '{')
            depth++;
        else if (*cursor == '}') {
            depth--;
            if (depth == 0)
                return cursor;
        }

        cursor++;
    }

    return NULL;
}

static bool
extract_section_bounds(const char* jsonText, const char* sectionName, const char** begin, const char** end)
{
    char sectionPattern[64];
    const char* sectionStart;
    const char* objectStart;
    const char* objectEnd;

    if ((jsonText == NULL) || (sectionName == NULL) || (begin == NULL) || (end == NULL))
        return false;

    snprintf(sectionPattern, sizeof(sectionPattern), "\"%s\"", sectionName);

    sectionStart = strstr(jsonText, sectionPattern);
    if (sectionStart == NULL)
        return false;

    objectStart = strchr(sectionStart, '{');
    if (objectStart == NULL)
        return false;

    objectEnd = find_matching_brace(objectStart);
    if (objectEnd == NULL)
        return false;

    *begin = objectStart + 1;
    *end = objectEnd;
    return true;
}

static bool
copy_json_string(const char** cursor, char* output, size_t outputSize)
{
    const char* start;
    size_t length;

    if ((cursor == NULL) || (*cursor == NULL) || (output == NULL) || (outputSize == 0))
        return false;

    if (**cursor != '"')
        return false;

    (*cursor)++;
    start = *cursor;

    while ((**cursor != '\0') && (**cursor != '"')) {
        if ((**cursor == '\\') && ((*cursor)[1] != '\0'))
            (*cursor)++;
        (*cursor)++;
    }

    if (**cursor != '"')
        return false;

    length = (size_t) (*cursor - start);
    if (length >= outputSize)
        length = outputSize - 1;

    memcpy(output, start, length);
    output[length] = '\0';
    (*cursor)++;
    return true;
}

static bool
copy_json_value(const char** cursor, const char* sectionEnd, char* output, size_t outputSize)
{
    const char* start;
    const char* end;
    size_t length;

    if ((cursor == NULL) || (*cursor == NULL) || (sectionEnd == NULL) || (output == NULL) || (outputSize == 0))
        return false;

    start = *cursor;

    if (*start == '"')
        return copy_json_string(cursor, output, outputSize);

    end = start;
    while ((end < sectionEnd) && (*end != ',') && (*end != '}'))
        end++;

    while ((end > start) && isspace((unsigned char) end[-1]))
        end--;

    length = (size_t) (end - start);
    if (length >= outputSize)
        length = outputSize - 1;

    memcpy(output, start, length);
    output[length] = '\0';
    *cursor = end;
    return true;
}

static bool
parse_json_object_section(const char* jsonText, const char* sectionName, EntryCallback callback, ServerContext* context)
{
    const char* cursor;
    const char* end;

    if (extract_section_bounds(jsonText, sectionName, &cursor, &end) == false)
        return false;

    while (cursor < end) {
        char key[160];
        char value[64];

        cursor = skip_whitespace(cursor);
        if ((cursor >= end) || (*cursor == '}'))
            break;

        if (copy_json_string(&cursor, key, sizeof(key)) == false)
            return false;

        cursor = skip_whitespace(cursor);
        if (*cursor != ':')
            return false;

        cursor++;
        cursor = skip_whitespace(cursor);

        if (copy_json_value(&cursor, end, value, sizeof(value)) == false)
            return false;

        if ((callback != NULL) && (callback(context, key, value) == false))
            return false;

        cursor = skip_whitespace(cursor);
        if (*cursor == ',')
            cursor++;
    }

    return true;
}

static bool
parse_updated_unix_ms(const char* jsonText, uint64_t* updatedUnixMs)
{
    const char* sectionStart;
    const char* valueStart;
    char* endPtr = NULL;
    unsigned long long parsedValue;

    if ((jsonText == NULL) || (updatedUnixMs == NULL))
        return false;

    sectionStart = strstr(jsonText, "\"updated_unix_ms\"");
    if (sectionStart == NULL)
        return false;

    valueStart = strchr(sectionStart, ':');
    if (valueStart == NULL)
        return false;

    valueStart = skip_whitespace(valueStart + 1);

    parsedValue = strtoull(valueStart, &endPtr, 10);
    if (endPtr == valueStart)
        return false;

    *updatedUnixMs = (uint64_t) parsedValue;
    return true;
}

static bool
tag_was_warned(ServerContext* context, const char* tag)
{
    size_t index;

    for (index = 0; index < context->warnedTagCount; index++) {
        if (strcmp(context->warnedTags[index], tag) == 0)
            return true;
    }

    return false;
}

static void
warn_missing_tag_once(ServerContext* context, const char* tag)
{
    if ((context == NULL) || (tag == NULL))
        return;

    if (tag_was_warned(context, tag))
        return;

    if (context->warnedTagCount < (sizeof(context->warnedTags) / sizeof(context->warnedTags[0]))) {
        snprintf(context->warnedTags[context->warnedTagCount], sizeof(context->warnedTags[0]), "%s", tag);
        context->warnedTagCount++;
    }

    printf("WARNING: model node not found for tag %s\n", tag);
}

static bool
normalize_tag_to_short_reference(const char* tag, char* output, size_t outputSize)
{
    const char* separator;
    size_t prefixLength;

    if ((tag == NULL) || (output == NULL) || (outputSize == 0))
        return false;

    separator = strchr(tag, '.');
    if (separator == NULL)
        return false;

    prefixLength = (size_t) (separator - tag);
    if ((prefixLength + strlen(separator) + 1) >= outputSize)
        return false;

    memcpy(output, tag, prefixLength);
    output[prefixLength] = '/';
    snprintf(output + prefixLength + 1, outputSize - prefixLength - 1, "%s", separator + 1);
    return true;
}

static bool
substitute_alias_reference(const char* relayType, const char* normalizedTag, char* output, size_t outputSize)
{
    const char* match;
    const char* search = ".SSCBR1.";
    const char* replacement = ".TCSSCBR1.";
    size_t prefixLength;

    if ((relayType == NULL) || (normalizedTag == NULL) || (output == NULL) || (outputSize == 0))
        return false;

    if (strcmp(relayType, "REF615") == 0)
        return false;

    match = strstr(normalizedTag, search);
    if (match == NULL)
        return false;

    prefixLength = (size_t) (match - normalizedTag);

    if ((prefixLength + strlen(replacement) + strlen(match + strlen(search)) + 1) >= outputSize)
        return false;

    memcpy(output, normalizedTag, prefixLength);
    output[prefixLength] = '\0';
    strcat(output, replacement);
    strcat(output, match + strlen(search));
    return true;
}

static DataAttribute*
resolve_attribute(ServerContext* context, const char* tag)
{
    char normalizedTag[192];
    char aliasTag[192];
    ModelNode* modelNode;

    if ((context == NULL) || (tag == NULL))
        return NULL;

    if (normalize_tag_to_short_reference(tag, normalizedTag, sizeof(normalizedTag)) == false)
        return NULL;

    modelNode = IedModel_getModelNodeByShortObjectReference(context->model, normalizedTag);
    if (modelNode != NULL)
        return (DataAttribute*) modelNode;

    if (substitute_alias_reference(context->relayType, normalizedTag, aliasTag, sizeof(aliasTag))) {
        modelNode = IedModel_getModelNodeByShortObjectReference(context->model, aliasTag);
        if (modelNode != NULL)
            return (DataAttribute*) modelNode;
    }

    warn_missing_tag_once(context, tag);
    return NULL;
}

static bool
handle_analog_entry(ServerContext* context, const char* key, const char* rawValue)
{
    DataAttribute* attribute;
    char* endPtr = NULL;
    float value;

    attribute = resolve_attribute(context, key);
    if (attribute == NULL)
        return true;

    value = strtof(rawValue, &endPtr);
    if (endPtr == rawValue)
        return false;

    IedServer_updateFloatAttributeValue(context->server, attribute, value);
    return true;
}

static bool
handle_bool_entry(ServerContext* context, const char* key, const char* rawValue)
{
    DataAttribute* attribute;
    bool value;

    attribute = resolve_attribute(context, key);
    if (attribute == NULL)
        return true;

    if (strcmp(rawValue, "true") == 0)
        value = true;
    else if (strcmp(rawValue, "false") == 0)
        value = false;
    else
        return false;

    IedServer_updateBooleanAttributeValue(context->server, attribute, value);
    return true;
}

static bool
handle_word_entry(ServerContext* context, const char* key, const char* rawValue)
{
    DataAttribute* attribute;
    char* endPtr = NULL;
    long value;

    attribute = resolve_attribute(context, key);
    if (attribute == NULL)
        return true;

    value = strtol(rawValue, &endPtr, 10);
    if (endPtr == rawValue)
        return false;

    IedServer_updateInt32AttributeValue(context->server, attribute, (int32_t) value);
    return true;
}

static bool
apply_json_values(ServerContext* context, const char* jsonText)
{
    uint64_t updatedUnixMs = 0;

    if ((context == NULL) || (jsonText == NULL))
        return false;

    if (parse_updated_unix_ms(jsonText, &updatedUnixMs) && (updatedUnixMs == context->lastUpdatedUnixMs))
        return true;

    IedServer_lockDataModel(context->server);

    if (parse_json_object_section(jsonText, "analogs", handle_analog_entry, context) == false) {
        IedServer_unlockDataModel(context->server);
        return false;
    }

    if (parse_json_object_section(jsonText, "bools", handle_bool_entry, context) == false) {
        IedServer_unlockDataModel(context->server);
        return false;
    }

    if (parse_json_object_section(jsonText, "words", handle_word_entry, context) == false) {
        IedServer_unlockDataModel(context->server);
        return false;
    }

    IedServer_unlockDataModel(context->server);

    if (updatedUnixMs != 0)
        context->lastUpdatedUnixMs = updatedUnixMs;

    return true;
}

static void
connection_handler(IedServer self, ClientConnection connection, bool connected, void* parameter)
{
    (void) self;
    (void) connection;
    (void) parameter;

    if (connected)
        printf("MMS client connected\n");
    else
        printf("MMS client disconnected\n");
}

int
main(int argc, char** argv)
{
    ProgramOptions options;
    ModelSelection selection;
    ServerContext context;
    IedServerConfig config = NULL;
    IedServer iedServer = NULL;
    char* runtimeIedName = NULL;

    if (parse_arguments(argc, argv, &options) == false) {
        print_usage(argv[0]);
        return 1;
    }

    selection = select_model(options.relayType);
    if (selection.model == NULL) {
        fprintf(stderr, "Unsupported relay type: %s\n", options.relayType);
        return 1;
    }

    runtimeIedName = duplicate_string(options.iedName);
    if (runtimeIedName == NULL) {
        fprintf(stderr, "Out of memory while preparing IED name\n");
        return 1;
    }

    IedModel_setIedName(selection.model, runtimeIedName);

    signal(SIGINT, handle_signal);
#ifdef SIGTERM
    signal(SIGTERM, handle_signal);
#endif

    config = IedServerConfig_create();
    IedServerConfig_enableFileService(config, false);
    IedServerConfig_enableLogService(config, false);
    IedServerConfig_enableDynamicDataSetService(config, true);
    IedServerConfig_setEdition(config, IEC_61850_EDITION_2);
    IedServerConfig_setMaxMmsConnections(config, 5);

    iedServer = IedServer_createWithConfig(selection.model, NULL, config);
    IedServerConfig_destroy(config);
    config = NULL;

    if (iedServer == NULL) {
        fprintf(stderr, "IedServer_createWithConfig failed\n");
        free(runtimeIedName);
        return 1;
    }

    IedServer_setConnectionIndicationHandler(iedServer, connection_handler, NULL);
    IedServer_setServerIdentity(iedServer, "KoffSim", options.relayType, "0.2");
    IedServer_setLocalIpAddress(iedServer, options.bindAddress);
    IedServer_disableGoosePublishing(iedServer);

    IedServer_start(iedServer, options.tcpPort);

    if (IedServer_isRunning(iedServer) == false) {
        fprintf(stderr, "IED server failed to start on %s:%d\n", options.bindAddress, options.tcpPort);
        IedServer_destroy(iedServer);
        free(runtimeIedName);
        return 1;
    }

    memset(&context, 0, sizeof(context));
    context.server = iedServer;
    context.model = selection.model;
    context.relayType = options.relayType;

    printf("IED %s (%s) listening on %s:%d\n", options.iedName, options.relayType, options.bindAddress, options.tcpPort);
    printf("Reading values from %s every 100 ms\n", options.valuesPath);

    while (g_running) {
        char* jsonText = read_text_file(options.valuesPath);

        if (jsonText != NULL) {
            if (apply_json_values(&context, jsonText) == false)
                printf("WARNING: failed to parse values file %s\n", options.valuesPath);

            free(jsonText);
        }

        Thread_sleep(100);
    }

    IedServer_stop(iedServer);
    IedServer_destroy(iedServer);
    free(runtimeIedName);
    return 0;
}