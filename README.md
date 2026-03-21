# Hyundai Sonata (YF) Cluster Connect

현대 YF쏘나타의 계기판과 게임과 연결하는 프로젝트입니다 <br>
본 코드는 모두 Claude를 통해 제작되었습니다
현재 지원하는 게임목록으로는
- Euro Truck
- Asseto Corsa
- BeamNG Drive

가 있습니다

필요한 준비물로는
- 계기판
- 12v 커넥터
- UCAN 보드
- 점퍼선

가 필요합니다

## 배선 설치
<img src="https://media.discordapp.net/attachments/998830932289142795/1478289438206333030/image.png?ex=69bf96d3&is=69be4553&hm=3f28dbe75d4771350eafe95a747208b42fe81c25b1a952a87e6eed5b2a344150&=&format=webp&quality=lossless&width=1737&height=1661">
위 사진은 계기판 배선도 입니다
26번핀과 29번 핀에 12v를 연결하고
31번핀과 32번 핀에 UCAN 보드를 연결하면 됩니다

## 처음 세팅법
```
1. "pip install -r requirements.txt" 를 프로젝트 파일 터미널에서 실행시켜줍니다
2. Zadig 를 통해 UCAN 드라이버를 설치해줍니다
```
추가로 유로트럭에서 사용할때는 몇가지 작업이 더 필요합니다
```
1. cd plugin
2. g++ -std=c++17 -O2 -shared -o ets2_bridge.dll ets2_bridge.cpp -I./sdk
3. copy ets2_bridge.dll "C:\...\Euro Truck Simulator 2\plugins\"
```
