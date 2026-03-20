CXX      = clang++
CXXFLAGS = -std=c++17 -O2 -Wall -fPIC -arch x86_64
LDFLAGS  = -dynamiclib

TARGET   = ets2_bridge.dylib
SRC      = ets2_bridge.cpp
INCLUDE  = -I./sdk

ETS2_PLUGINS = $(HOME)/Library/Application Support/Steam/steamapps/common/Euro Truck Simulator 2/plugins

$(TARGET): $(SRC)
	$(CXX) $(CXXFLAGS) $(LDFLAGS) $(INCLUDE) -o $@ $^
	@echo "빌드 완료: $(TARGET)"

install: $(TARGET)
	@mkdir -p "$(ETS2_PLUGINS)"
	cp $(TARGET) "$(ETS2_PLUGINS)/"
	@echo "설치 완료: $(ETS2_PLUGINS)/$(TARGET)"

clean:
	rm -f $(TARGET)

.PHONY: install clean
