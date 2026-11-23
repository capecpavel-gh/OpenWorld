// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "OpenWorldGameMode.generated.h"

class AOpenWorldProp;

/**
 *  Simple GameMode for a third person game
 */
UCLASS(abstract)
class AOpenWorldGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:

	/** Constructor */
	AOpenWorldGameMode();

	/**
	 *  Spawns a solid test object standing on the ground at a location.
	 *  Substance: "Wood" or "Steel". Shape: "Post", "Block", "Crate" (the crate can be knocked around) or "Shield".
	 */
	UFUNCTION(BlueprintCallable, Category="Testing")
	AOpenWorldProp* SpawnTestProp(FName Substance, FName Shape, FVector GroundLocation, float Yaw = 0.f);

protected:

	virtual void BeginPlay() override;

	/** Put a row of wood and steel objects in front of the player start, to try weapon contacts on */
	UPROPERTY(EditAnywhere, Category="Testing")
	bool bSpawnTestProps = true;

	/** Distance of the row of test objects from the player start */
	UPROPERTY(EditAnywhere, Category="Testing", meta=(Units="cm"))
	float TestPropDistance = 350.f;

	/** Gap between neighbouring test objects */
	UPROPERTY(EditAnywhere, Category="Testing", meta=(Units="cm"))
	float TestPropSpacing = 170.f;
};
