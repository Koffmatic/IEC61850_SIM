#include "iec61850_model.h"
#include "iec61850_server.h"
#include "hal_thread.h"
#include "static_model.h"

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
    char* jsonText;
    size_t jsonSize;
} ValuesSnapshot;

static volatile sig_atomic_t g_running = 1;

static void print_usage(const char* programName)
{
    printf("Usage: %s --ied-name <name> --type <type> --bind <ip> --port <port> --values <path>\n", programName);
}

static void handle_signal(int signalId)
{
    (void) signalId;
    g_running = 0;
}

static char* duplicate_string(const char* value)
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

static bool parse_int_value(const char* text, int* outValue)
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

static bool parse_arguments(int argc, char** argv, ProgramOptions* options)
{
    int argIndex;

    if (options == NULL)
        return false;

    options->iedName = NULL;
    options->relayType = NULL;
    options->bindAddress = NULL;
    options->tcpPort = 102;
    options->valuesPath = NULL;

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

    if ((options->iedName == NULL) || (options->relayType == NULL) ||
        (options->bindAddress == NULL) || (options->valuesPath == NULL)) {
        return false;
    }

    return true;
}

static void free_values_snapshot(ValuesSnapshot* snapshot)
{
    if ((snapshot != NULL) && (snapshot->jsonText != NULL)) {
        free(snapshot->jsonText);
        snapshot->jsonText = NULL;
        snapshot->jsonSize = 0;
    }
}

static bool load_values_snapshot(const char* path, ValuesSnapshot* snapshot)
{
    FILE* fileHandle;
    long fileSize;
    size_t bytesRead;

    if ((path == NULL) || (snapshot == NULL))
        return false;

    snapshot->jsonText = NULL;
    snapshot->jsonSize = 0;

    fileHandle = fopen(path, "rb");
    if (fileHandle == NULL)
        return false;

    if (fseek(fileHandle, 0, SEEK_END) != 0) {
        fclose(fileHandle);
        return false;
    }

    fileSize = ftell(fileHandle);
    if (fileSize < 0) {
        fclose(fileHandle);
        return false;
    }

    if (fseek(fileHandle, 0, SEEK_SET) != 0) {
        fclose(fileHandle);
        return false;
    }

    snapshot->jsonText = (char*) malloc((size_t) fileSize + 1u);
    if (snapshot->jsonText == NULL) {
        fclose(fileHandle);
        return false;
    }

    bytesRead = fread(snapshot->jsonText, 1, (size_t) fileSize, fileHandle);
    fclose(fileHandle);

    if (bytesRead != (size_t) fileSize) {
        free_values_snapshot(snapshot);
        return false;
    }

    snapshot->jsonText[fileSize] = '\0';
    snapshot->jsonSize = (size_t) fileSize;
    return true;
}

static void apply_values_snapshot(IedServer iedServer, const ProgramOptions* options, const ValuesSnapshot* snapshot)
{
    (void) iedServer;
    (void) options;

    if ((snapshot == NULL) || (snapshot->jsonText == NULL))
        return;

    /*
     * TODO: Parse snapshot->jsonText and map JSON tags to the generated handles in static_model.h.
     *
     * Expected values JSON structure:
     * {
     *   "analogs": {"LD0.CMMXU1.A.phsA.instCVal.mag.f": 18.4, ...},
     *   "bools":   {"LD0.LEDGGIO1.Ind1.stVal": true, ...},
     *   "words":   {"LD0.SSCBR1.Beh.stVal": 1, ...},
     *   "updated_unix_ms": 1715420000000
     * }
     *
     * The DataAttribute handle names depend on the SCL/ICD/CID model generator output,
     * so do not hardcode them until static_model.h is available for your exact model.
     *
     * Typical update points once the model handles are known:
     *   IedServer_updateFloatAttributeValue(iedServer, <DATA_ATTRIBUTE_HANDLE>, floatValue);
     *   IedServer_updateBooleanAttributeValue(iedServer, <DATA_ATTRIBUTE_HANDLE>, boolValue);
     *   IedServer_updateInt32AttributeValue(iedServer, <DATA_ATTRIBUTE_HANDLE>, intValue);
     */
}

int main(int argc, char** argv)
{
    ProgramOptions options;
    IedServer iedServer = NULL;
    char* runtimeIedName = NULL;

    if (parse_arguments(argc, argv, &options) == false) {
        print_usage(argv[0]);
        return 1;
    }

    signal(SIGINT, handle_signal);
#ifdef SIGTERM
    signal(SIGTERM, handle_signal);
#endif

    runtimeIedName = duplicate_string(options.iedName);
    if (runtimeIedName == NULL) {
        fprintf(stderr, "Out of memory while preparing IED name\n");
        return 1;
    }

    IedModel_setIedName(&iedModel, runtimeIedName);

    iedServer = IedServer_create(&iedModel);
    if (iedServer == NULL) {
        fprintf(stderr, "IedServer_create failed\n");
        free(runtimeIedName);
        return 1;
    }

    IedServer_disableGoosePublishing(iedServer);
    IedServer_setLocalIpAddress(iedServer, options.bindAddress);
    IedServer_setServerIdentity(iedServer, "Template", options.relayType, "0.1");
    IedServer_start(iedServer, options.tcpPort);

    if (IedServer_isRunning(iedServer) == false) {
        fprintf(stderr, "IED server failed to start on %s:%d\n", options.bindAddress, options.tcpPort);
        IedServer_destroy(iedServer);
        free(runtimeIedName);
        return 1;
    }

    printf("IED %s (%s) listening on %s:%d\n", options.iedName, options.relayType, options.bindAddress, options.tcpPort);
    printf("Reading values from %s every 100 ms\n", options.valuesPath);

    while (g_running) {
        ValuesSnapshot snapshot;

        if (load_values_snapshot(options.valuesPath, &snapshot)) {
            IedServer_lockDataModel(iedServer);
            apply_values_snapshot(iedServer, &options, &snapshot);
            IedServer_unlockDataModel(iedServer);
            free_values_snapshot(&snapshot);
        }

        Thread_sleep(100);
    }

    IedServer_stop(iedServer);
    IedServer_destroy(iedServer);
    free(runtimeIedName);
    return 0;
}